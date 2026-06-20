import fitz
import os
import re
import tempfile
import time
import uuid
from typing import Iterable, Iterator, List, Dict, Any

from app.services.pdf_export_utils import pixmap_to_export_image_bytes, write_optimized_pdf
from app.services.pdf_font_utils import detect_page_required_scripts, resolve_translation_font_paths
from app.services.pdf_font_utils import TranslationFontConfigurationError
from app.services.pdf_layout_analyzer import PDFLayoutAnalyzer
from app.services.pdf_layout_utils import (
    color_from_int,
    ensure_readable_color,
    rect_overlap_ratio,
)
from app.services.pdf_text_utils import (
    CJK_PUNCTUATION,
    MARKER_GLYPHS,
    SENTENCE_ENDINGS,
    has_cjk,
    is_symbol_emoji,
    is_symbol_emoji_text,
    normalize_pdf_text,
)
from app.services.translation_text_utils import sanitize_translated_text
from app.services.storage_service import storage_service


def _pdf_perf_log(event: str, **fields) -> None:
    if os.getenv("PDF_PERF_LOGS", "1").strip().lower() in {"0", "false", "off"}:
        return

    details = " ".join(f"{key}={value}" for key, value in fields.items() if value is not None)
    print(f"[PERF] PDF {event}: {details}".rstrip())


def _elapsed_ms(started_at: float) -> int:
    return int((time.perf_counter() - started_at) * 1000)


REFERENCE_SUPERSCRIPT_CHARS = "\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078\u2079"
REFERENCE_RENDER_MARKER_RE = re.compile(
    rf"[{REFERENCE_SUPERSCRIPT_CHARS}]+(?:[,\.\-\u2013\u2014][{REFERENCE_SUPERSCRIPT_CHARS}]+)*"
)
REFERENCE_RENDER_TRANSLATION = str.maketrans({
    "\u2070": "0",
    "\u00b9": "1",
    "\u00b2": "2",
    "\u00b3": "3",
    "\u2074": "4",
    "\u2075": "5",
    "\u2076": "6",
    "\u2077": "7",
    "\u2078": "8",
    "\u2079": "9",
})


class PDFService(PDFLayoutAnalyzer):
    def __init__(self):
        self.upload_dir = os.path.join(os.path.dirname(__file__), "..", "..", "uploads")
        self.output_dir = os.path.join(os.path.dirname(__file__), "..", "..", "outputs")
        os.makedirs(self.upload_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)
        self._background_pixmap_cache = {}
        self._page_image_rect_cache = {}

    PREVIEW_VISUAL_LAYER_SCALE = 1.25
    TRANSLATED_EXPORT_BATCH_SIZE = 100
    BILINGUAL_EXPORT_BATCH_SIZE = 50

    def get_file_storage_key(self, file_id: str) -> str:
        return f"uploads/{file_id}.pdf"

    def get_output_storage_key(self, task_id: str) -> str:
        return f"outputs/{task_id}.json"

    def get_output_page_storage_key(self, task_id: str, page_num: int) -> str:
        return f"outputs/{task_id}/pages/{page_num + 1}.json"

    def get_export_pdf_storage_key(self, task_id: str, output_type: str) -> str:
        safe_output_type = "bilingual" if output_type == "bilingual" else "translated"
        return f"outputs/{task_id}/exports/{safe_output_type}.pdf"

    def get_export_quality_storage_key(self, task_id: str, output_type: str) -> str:
        safe_output_type = "bilingual" if output_type == "bilingual" else "translated"
        return f"outputs/{task_id}/exports/{safe_output_type}.quality.json"
    
    def save_uploaded_file(self, file_content: bytes) -> str:
        file_id = str(uuid.uuid4())
        storage_service.save_bytes(self.get_file_storage_key(file_id), file_content)
        return file_id
    
    def get_file_path(self, file_id: str) -> str:
        return storage_service.get_local_path(self.get_file_storage_key(file_id))
    
    def get_output_path(self, task_id: str) -> str:
        return storage_service.get_local_path(self.get_output_storage_key(task_id))
    
    def get_total_pages(self, file_id: str) -> int:
        file_path = self.get_file_path(file_id)
        if not os.path.exists(file_path):
            raise FileNotFoundError("File not found")
        
        doc = fitz.open(file_path)
        total_pages = len(doc)
        doc.close()
        return total_pages

    def generate_page_preview_png(self, file_id: str, page_num: int = 0, max_width: int = 1400) -> bytes:
        file_path = self.get_file_path(file_id)
        if not os.path.exists(file_path):
            raise FileNotFoundError("File not found")

        return self.generate_pdf_file_page_preview_png(file_path, page_num, max_width=max_width)

    def generate_pdf_file_page_preview_png(self, pdf_path: str, page_num: int = 0, max_width: int = 1400) -> bytes:
        if not os.path.exists(pdf_path):
            raise FileNotFoundError("File not found")

        doc = fitz.open(pdf_path)
        try:
            if page_num < 0 or page_num >= len(doc):
                raise ValueError("Invalid page number")

            page = doc[page_num]
            page_width = max(float(page.rect.width), 1.0)
            target_width = max(int(max_width), 400)
            zoom = min(target_width / page_width, 2.0)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            return pixmap.tobytes("png")
        finally:
            doc.close()

    def generate_cached_export_page_preview_png(
        self,
        task_id: str,
        output_type: str,
        page_num: int = 0,
        max_width: int = 1800,
    ) -> bytes:
        export_path = self.get_cached_export_pdf_path(task_id, output_type)
        return self.generate_pdf_file_page_preview_png(export_path, page_num, max_width=max_width)
    
    def extract_text_blocks(self, file_id: str, page_num: int) -> List[Dict[str, Any]]:
        file_path = self.get_file_path(file_id)
        if not os.path.exists(file_path):
            raise FileNotFoundError("File not found")
        
        doc = fitz.open(file_path)
        if page_num < 0 or page_num >= len(doc):
            raise ValueError("Invalid page number")
        
        page = doc[page_num]
        page_rect = page.rect
        text_blocks = []
        
        # Use get_text("rawdict") to preserve span-level font, position, and
        # character gaps. Some PDFs encode spaces as horizontal offsets.
        text_info = page.get_text("rawdict")
        graphic_regions = self._collect_graphic_regions(page, text_info)
        table_rule_regions = self._collect_table_rule_regions(page)
        
        for block in text_info.get("blocks", []):
            block_lines = []
            
            for line in block.get("lines", []):
                line_text_parts = []
                line_spans = []
                line_font_size = 0
                line_x0, line_y0, line_x1, line_y1 = float('inf'), float('inf'), 0, 0

                spans = line.get("spans", [])
                for span_index, span in enumerate(spans):
                    text = self._span_text(span).strip()
                    if not text:
                        continue

                    previous_text = " ".join(line_text_parts[-2:])
                    next_span = None
                    for candidate_span in spans[span_index + 1:]:
                        if self._span_text(candidate_span).strip():
                            next_span = candidate_span
                            break
                    if next_span is not None:
                        text = self._repair_symbol_span_text(text, span, previous_text, next_span)
                    
                    decorative_chars = {"/", "-", "\u2013", "\u2014", "\u2022", "\u00b7", "|", " "}
                    span_size = float(span.get("size") or 0)
                    reference_marker = self._looks_like_reference_marker_text(text, span_size)
                    is_inline_reference_marker = self._looks_like_inline_reference_marker(text, span, line_spans)
                    is_decorative = len(text) == 1 and text in decorative_chars
                    
                    if is_decorative or (reference_marker and not line_spans):
                        continue

                    span_text = self._format_reference_marker_text(text) if is_inline_reference_marker else text
                    
                    line_text_parts.append(span_text)
                    line_font_size = max(line_font_size, span.get("size", 0))
                    line_x0 = min(line_x0, span["bbox"][0])
                    line_y0 = min(line_y0, span["bbox"][1])
                    line_x1 = max(line_x1, span["bbox"][2])
                    line_y1 = max(line_y1, span["bbox"][3])
                    line_spans.append({
                        "text": span_text,
                        "source_text": text,
                        "is_reference_marker": is_inline_reference_marker,
                        "char_bboxes": self._span_char_bboxes(span),
                        "bbox": {
                            "x0": span["bbox"][0],
                            "y0": span["bbox"][1],
                            "x1": span["bbox"][2],
                            "y1": span["bbox"][3],
                        },
                        "font": span.get("font"),
                        "font_size": span.get("size", 0),
                        "color": span.get("color", 0),
                        "flags": span.get("flags", 0),
                    })
                if line_text_parts:
                    line_text = self._compose_line_text_from_spans(line_spans)
                    block_lines.append({
                        "text": line_text,
                        "bbox": {"x0": line_x0, "y0": line_y0, "x1": line_x1, "y1": line_y1},
                        "font_size": line_font_size,
                        "spans": line_spans,
                    })
            
            if block_lines:
                for block_payload in self._split_text_block_from_lines(block_lines, page_rect, page_num):
                    text_blocks.append(block_payload)
        
        text_blocks.sort(key=lambda b: (b["bbox"]["y0"], b["bbox"]["x0"]))
        text_blocks = self._merge_text_blocks(text_blocks)
        self._refine_dense_reference_flags(text_blocks, page_rect)
        self._refine_header_footer_metadata_flags(text_blocks)
        self._mark_chart_text_blocks(text_blocks, page_rect, graphic_regions)
        self._mark_table_text_blocks(text_blocks, page_rect, table_rule_regions)
        
        doc.close()
        return text_blocks
    
    def extract_full_text(self, file_id: str, page_num: int) -> str:
        file_path = self.get_file_path(file_id)
        if not os.path.exists(file_path):
            raise FileNotFoundError("File not found")
        
        doc = fitz.open(file_path)
        if page_num < 0 or page_num >= len(doc):
            raise ValueError("Invalid page number")
        
        page = doc[page_num]
        text = page.get_text()
        doc.close()
        return text

    def extract_page_content(self, file_id: str, page_num: int) -> Dict[str, Any]:
        return {
            "fullText": self.extract_full_text(file_id, page_num),
            "textBlocks": self.extract_text_blocks(file_id, page_num),
        }
    
    def save_translation_result(self, task_id: str, result: Dict[str, Any]):
        import json
        content = json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")
        storage_service.save_bytes(self.get_output_storage_key(task_id), content)
        self.delete_cached_export_pdfs(task_id)

    def save_page_translation_result(self, task_id: str, page_num: int, result: Dict[str, Any]) -> None:
        import json
        content = json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")
        storage_service.save_bytes(self.get_output_page_storage_key(task_id, page_num), content)

    def load_page_translation_result(self, task_id: str, page_num: int) -> Dict[str, Any]:
        storage_key = self.get_output_page_storage_key(task_id, page_num)
        if not storage_service.exists(storage_key):
            raise FileNotFoundError("Page result not found")

        import json
        return json.loads(storage_service.read_bytes(storage_key).decode("utf-8"))
    
    def load_translation_result(self, task_id: str) -> Dict[str, Any]:
        storage_key = self.get_output_storage_key(task_id)
        if not storage_service.exists(storage_key):
            raise FileNotFoundError("Result not found")
        
        import json
        return json.loads(storage_service.read_bytes(storage_key).decode("utf-8"))

    def load_translation_result_with_pages(self, task_id: str) -> Dict[str, Any]:
        result = self.load_translation_result(task_id)
        page_results = self.load_page_translation_results(task_id)
        if not page_results:
            raise FileNotFoundError("Page results not found")

        result = dict(result)
        result["pages"] = sorted(page_results, key=lambda page: page.get("pageNum", 0))
        return result

    def load_page_translation_results(self, task_id: str) -> List[Dict[str, Any]]:
        import json

        page_results: List[Dict[str, Any]] = []
        page_num = 0
        while True:
            storage_key = self.get_output_page_storage_key(task_id, page_num)
            if not storage_service.exists(storage_key):
                break
            page_results.append(json.loads(storage_service.read_bytes(storage_key).decode("utf-8")))
            page_num += 1
        return page_results

    def iter_page_translation_results(self, task_id: str, page_count: int = None) -> Iterator[Dict[str, Any]]:
        if page_count is None:
            result = self.load_translation_result(task_id)
            page_count = int(
                result.get("translatedPages")
                or result.get("requestedPages")
                or result.get("totalPages")
                or 0
            )

        for page_num in range(max(page_count, 0)):
            yield self.load_page_translation_result(task_id, page_num)

    def has_cached_export_pdf(self, task_id: str, output_type: str) -> bool:
        return storage_service.exists(self.get_export_pdf_storage_key(task_id, output_type))

    def get_cached_export_pdf_path(self, task_id: str, output_type: str) -> str:
        return storage_service.get_local_path(self.get_export_pdf_storage_key(task_id, output_type))

    def load_cached_export_pdf(self, task_id: str, output_type: str) -> bytes:
        return storage_service.read_bytes(self.get_export_pdf_storage_key(task_id, output_type))

    def save_cached_export_pdf(self, task_id: str, output_type: str, pdf_bytes: bytes) -> None:
        storage_service.save_bytes(self.get_export_pdf_storage_key(task_id, output_type), pdf_bytes)

    def save_cached_export_pdf_file(self, task_id: str, output_type: str, pdf_path: str) -> None:
        storage_service.save_file(self.get_export_pdf_storage_key(task_id, output_type), pdf_path)

    def save_export_quality_report(self, task_id: str, output_type: str, report: Dict[str, Any]) -> None:
        import json
        content = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
        storage_service.save_bytes(self.get_export_quality_storage_key(task_id, output_type), content)

    def has_export_quality_report(self, task_id: str, output_type: str) -> bool:
        return storage_service.exists(self.get_export_quality_storage_key(task_id, output_type))

    def load_export_quality_report(self, task_id: str, output_type: str) -> Dict[str, Any]:
        import json
        return json.loads(storage_service.read_bytes(self.get_export_quality_storage_key(task_id, output_type)).decode("utf-8"))

    def delete_cached_export_pdfs(self, task_id: str) -> None:
        for output_type in ("translated", "bilingual"):
            storage_key = self.get_export_pdf_storage_key(task_id, output_type)
            if storage_service.exists(storage_key):
                storage_service.delete(storage_key)
            quality_storage_key = self.get_export_quality_storage_key(task_id, output_type)
            if storage_service.exists(quality_storage_key):
                storage_service.delete(quality_storage_key)

    def _clear_render_caches(self) -> None:
        self._background_pixmap_cache.clear()
        self._page_image_rect_cache.clear()

    def _get_page_image_rects(self, page) -> List[fitz.Rect]:
        page_number = page.number
        if page_number is None:
            return []

        key = (id(page.parent), page_number)
        cached = self._page_image_rect_cache.get(key)
        if cached is not None:
            return cached

        rects: List[fitz.Rect] = []
        try:
            page_dict = page.get_text("dict")
        except Exception:
            self._page_image_rect_cache[key] = rects
            return rects

        for raw_block in page_dict.get("blocks", []):
            if raw_block.get("type") != 1:
                continue
            bbox = raw_block.get("bbox")
            if not bbox or len(bbox) != 4:
                continue
            rect = fitz.Rect(*bbox)
            if not rect.is_empty and rect.width > 0 and rect.height > 0:
                rects.append(rect)

        if len(self._page_image_rect_cache) > 12:
            self._page_image_rect_cache.clear()
        self._page_image_rect_cache[key] = rects
        return rects

    def _get_background_pixmap(self, page, scale: float = 0.35):
        page_number = page.number
        if page_number is None:
            return None

        key = (id(page.parent), page_number, scale)
        cached = self._background_pixmap_cache.get(key)
        if cached is not None:
            return cached

        if len(self._background_pixmap_cache) > 12:
            self._background_pixmap_cache.clear()

        pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        cached = (pixmap, scale)
        self._background_pixmap_cache[key] = cached
        return cached

    def _estimate_background_color(self, page, rect: fitz.Rect, source_block: Dict[str, Any] = None):
        text_colors = []
        if source_block:
            for line in source_block.get("lines", []):
                for span in line.get("spans", []):
                    if span.get("text", "").strip():
                        text_colors.append(color_from_int(span.get("color", 0)))
        text_color_buckets = set()
        for text_color in text_colors:
            try:
                red = int(max(0, min(255, round(text_color[0] * 255))))
                green = int(max(0, min(255, round(text_color[1] * 255))))
                blue = int(max(0, min(255, round(text_color[2] * 255))))
            except Exception:
                continue
            base_bucket = (red // 16, green // 16, blue // 16)
            for red_delta in (-1, 0, 1):
                for green_delta in (-1, 0, 1):
                    for blue_delta in (-1, 0, 1):
                        text_color_buckets.add((
                            max(0, min(15, base_bucket[0] + red_delta)),
                            max(0, min(15, base_bucket[1] + green_delta)),
                            max(0, min(15, base_bucket[2] + blue_delta)),
                        ))

        clip_rect = fitz.Rect(
            max(page.rect.x0, rect.x0 - 4),
            max(page.rect.y0, rect.y0 - 4),
            min(page.rect.x1, rect.x1 + 4),
            min(page.rect.y1, rect.y1 + 4),
        )
        if clip_rect.is_empty:
            return fitz.utils.getColor("white")

        try:
            cached_background = self._get_background_pixmap(page)
        except Exception:
            return fitz.utils.getColor("white")
        if not cached_background:
            return fitz.utils.getColor("white")

        counts = {}
        fallback_counts = {}
        pixmap, scale = cached_background
        channels = pixmap.n
        if pixmap.width <= 0 or pixmap.height <= 0 or channels < 3:
            return fitz.utils.getColor("white")

        x0 = max(0, min(pixmap.width - 1, int((clip_rect.x0 - page.rect.x0) * scale)))
        y0 = max(0, min(pixmap.height - 1, int((clip_rect.y0 - page.rect.y0) * scale)))
        x1 = max(x0 + 1, min(pixmap.width, int((clip_rect.x1 - page.rect.x0) * scale) + 1))
        y1 = max(y0 + 1, min(pixmap.height, int((clip_rect.y1 - page.rect.y0) * scale) + 1))
        sample_area = max((x1 - x0) * (y1 - y0), 1)
        step = max(1, int((sample_area / 5000) ** 0.5))
        samples = pixmap.samples
        def add_sample(aggregates, bucket, red, green, blue):
            if bucket not in aggregates:
                aggregates[bucket] = [0, 0, 0, 0]
            aggregates[bucket][0] += 1
            aggregates[bucket][1] += red
            aggregates[bucket][2] += green
            aggregates[bucket][3] += blue

        for y in range(y0, y1, step):
            row_offset = y * pixmap.width * channels
            for x in range(x0, x1, step):
                offset = row_offset + x * channels
                red, green, blue = samples[offset], samples[offset + 1], samples[offset + 2]
                bucket_index = (red // 16, green // 16, blue // 16)
                bucket = (bucket_index[0] * 16, bucket_index[1] * 16, bucket_index[2] * 16)
                add_sample(fallback_counts, bucket, red, green, blue)

                if bucket_index in text_color_buckets:
                    continue
                add_sample(counts, bucket, red, green, blue)

        usable_counts = counts or fallback_counts
        if not usable_counts:
            return fitz.utils.getColor("white")

        dominant = max(usable_counts, key=lambda bucket: usable_counts[bucket][0])
        count, red_sum, green_sum, blue_sum = usable_counts[dominant]
        background = (red_sum / count / 255, green_sum / count / 255, blue_sum / count / 255)
        if min(background) > 0.94:
            return fitz.utils.getColor("white")
        return background

    def _is_bold_span(self, span: Dict[str, Any]) -> bool:
        font_name = (span.get("font") or "").lower()
        flags = int(span.get("flags") or 0)
        bold_names = ["bold", "black", "heavy", "semibold", "demibold", "extrabold"]
        return bool(flags & 16) or any(name in font_name for name in bold_names)

    def _detect_block_alignment(self, page, rect: fitz.Rect, source_block: Dict[str, Any] = None) -> int:
        page_width = page.rect.width
        if page_width <= 0 or rect.width <= 0:
            return fitz.TEXT_ALIGN_LEFT

        if source_block:
            line_rects = []
            line_sizes = []
            for line in source_block.get("lines", []):
                if not normalize_pdf_text(line.get("text", "")):
                    continue
                bbox = line.get("bbox")
                if not bbox:
                    continue
                try:
                    line_rects.append(fitz.Rect(bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"]))
                    if line.get("font_size"):
                        line_sizes.append(float(line.get("font_size")))
                except Exception:
                    continue

            clean_text = normalize_pdf_text(source_block.get("text", ""))
            line_count = len(line_rects)
            median_size = sorted(line_sizes)[len(line_sizes) // 2] if line_sizes else max(rect.height, 10)
            layout_role = source_block.get("layout_role", "body")

            if layout_role == "body" and line_count == 1:
                return fitz.TEXT_ALIGN_LEFT

            if line_count > 1:
                x0_range = max(line.x0 for line in line_rects) - min(line.x0 for line in line_rects)
                center_range = (
                    max(line.x0 + line.width / 2 for line in line_rects) -
                    min(line.x0 + line.width / 2 for line in line_rects)
                )
                block_center = rect.x0 + rect.width / 2
                page_center = page.rect.x0 + page_width / 2

                if len(clean_text) > 80:
                    return fitz.TEXT_ALIGN_LEFT
                if center_range <= median_size * 0.8 and abs(block_center - page_center) <= page_width * 0.1:
                    return fitz.TEXT_ALIGN_CENTER
                if x0_range <= median_size * 0.8:
                    return fitz.TEXT_ALIGN_LEFT

            if line_count > 1 and len(clean_text) > 80:
                return fitz.TEXT_ALIGN_LEFT

        block_center = rect.x0 + rect.width / 2
        page_center = page.rect.x0 + page_width / 2
        center_delta = abs(block_center - page_center)
        left_margin = max(0, rect.x0 - page.rect.x0)
        right_margin = max(0, page.rect.x1 - rect.x1)

        if (
            center_delta <= page_width * 0.08
            and abs(left_margin - right_margin) <= page_width * 0.18
            and rect.width <= page_width * 0.85
        ):
            return fitz.TEXT_ALIGN_CENTER

        if (
            right_margin <= page_width * 0.08
            and left_margin > right_margin * 2.5
            and rect.width <= page_width * 0.75
        ):
            return fitz.TEXT_ALIGN_RIGHT

        return fitz.TEXT_ALIGN_LEFT

    def _get_block_style(
        self,
        page,
        rect: fitz.Rect,
        fallback_font_size: float = 10,
        source_block: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        sizes = []
        color_weights = {}
        fonts = []
        bold_weight = 0
        total_weight = 0
        first_color = None

        if source_block:
            for line in source_block.get("lines", []):
                for span in line.get("spans", []):
                    span_text = span.get("text", "").strip()
                    if not span_text:
                        continue

                    color = span.get("color", 0)
                    if first_color is None:
                        first_color = color
                    text_weight = max(len(span_text), 1)
                    sizes.append(span.get("font_size", span.get("size", fallback_font_size)))
                    color_weights[color] = color_weights.get(color, 0) + text_weight
                    fonts.append(span.get("font", ""))
                    total_weight += text_weight
                    if self._is_bold_span(span):
                        bold_weight += text_weight

        if not sizes:
            text_info = page.get_text("dict")
            for block in text_info.get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        span_text = span.get("text", "").strip()
                        if not span_text:
                            continue

                        span_rect = fitz.Rect(span["bbox"])
                        if rect_overlap_ratio(span_rect, rect) < 0.2:
                            continue

                        color = span.get("color", 0)
                        if first_color is None:
                            first_color = color
                        text_weight = max(len(span_text), 1)
                        sizes.append(span.get("size", fallback_font_size))
                        color_weights[color] = color_weights.get(color, 0) + text_weight
                        fonts.append(span.get("font", ""))
                        total_weight += text_weight
                        if self._is_bold_span(span):
                            bold_weight += text_weight

        if sizes:
            sorted_sizes = sorted(sizes)
            font_size = sorted_sizes[len(sorted_sizes) // 2]
        else:
            font_size = fallback_font_size

        dominant_color = max(color_weights, key=color_weights.get) if color_weights else 0
        total_color_weight = sum(color_weights.values())
        dominant_ratio = (
            color_weights.get(dominant_color, 0) / total_color_weight
            if total_color_weight
            else 1
        )
        base_color = (
            first_color
            if first_color is not None and len(color_weights) > 1 and dominant_ratio < 0.75
            else dominant_color
        )
        color = color_from_int(base_color) if color_weights else fitz.utils.getColor("black")
        font_name = fonts[0] if fonts else ""
        background_color = self._estimate_background_color(page, rect, source_block)

        return {
            "font_size": max(font_size, 6),
            "color": ensure_readable_color(color, background_color),
            "background_color": background_color,
            "font_name": font_name,
            "is_bold": bool(total_weight and bold_weight / total_weight >= 0.45),
            "align": self._detect_block_alignment(page, rect, source_block),
        }

    def _split_leading_marker(self, translated_text: str, source_text: str):
        translated_marker, translated, translated_has_marker = self._split_marker_prefix(translated_text)
        source_marker, _, source_has_marker = self._split_marker_prefix(source_text)
        translated_visual_marker, translated_visual, translated_has_visual_marker = (
            self._split_preserved_visual_marker_prefix(translated_text)
        )
        source_visual_marker, _, source_has_visual_marker = self._split_preserved_visual_marker_prefix(source_text)

        marker = ""
        if translated_has_marker:
            marker = translated_marker
        elif source_has_marker:
            marker = source_marker
            translated = self._strip_render_marker_prefix(translated_text)
        elif translated_has_visual_marker:
            marker = translated_visual_marker
            translated = translated_visual
        elif source_has_visual_marker:
            marker = source_visual_marker
            translated = self._strip_render_marker_prefix(translated_text)

        return marker, translated

    def _span_char_bboxes(self, span: Dict[str, Any]) -> List[Dict[str, Any]]:
        char_bboxes: List[Dict[str, Any]] = []
        for char in span.get("chars") or []:
            value = str(char.get("c", ""))
            bbox = char.get("bbox")
            if not value or bbox is None:
                continue
            try:
                char_bboxes.append({
                    "char": value,
                    "bbox": {
                        "x0": float(bbox[0]),
                        "y0": float(bbox[1]),
                        "x1": float(bbox[2]),
                        "y1": float(bbox[3]),
                    },
                })
            except Exception:
                continue
        return char_bboxes

    def _rect_from_bbox_mapping(self, bbox: Dict[str, Any]) -> fitz.Rect:
        return fitz.Rect(bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"])

    def _span_text_rects_without_symbol_emoji(self, span: Dict[str, Any]) -> List[fitz.Rect]:
        char_rects: List[fitz.Rect] = []
        for char_info in span.get("char_bboxes") or []:
            char = str(char_info.get("char") or "")
            if not char or char in {"\ufe0f", "\u200d"} or is_symbol_emoji(char):
                continue
            bbox = char_info.get("bbox")
            if not bbox:
                continue
            try:
                char_rect = self._rect_from_bbox_mapping(bbox)
            except Exception:
                continue
            if not char_rect.is_empty:
                char_rects.append(char_rect)

        if char_rects:
            return char_rects

        span_text = normalize_pdf_text(span.get("text", ""))
        if not span_text or is_symbol_emoji_text(span_text):
            return []

        bbox = span.get("bbox")
        if not bbox:
            return []
        try:
            span_rect = self._rect_from_bbox_mapping(bbox)
        except Exception:
            return []
        return [] if span_rect.is_empty else [span_rect]

    def _split_preserved_visual_marker_prefix(self, text: str):
        clean_text = normalize_pdf_text(text)
        marker_chars = []
        saw_visual = False
        saw_prefix = False
        index = 0

        while index < len(clean_text):
            char = clean_text[index]
            if char.isspace() and saw_prefix:
                index += 1
                continue
            if char in {"\x00", "\ufffd", "\ufe0f", "\u200d"}:
                saw_prefix = True
                index += 1
                continue
            if char in MARKER_GLYPHS or is_symbol_emoji(char):
                saw_prefix = True
                if is_symbol_emoji(char):
                    saw_visual = True
                marker_chars.append(char)
                index += 1
                continue
            break

        if not saw_visual:
            return "", clean_text, False

        marker = "".join(marker_chars) or "\u2022"
        return marker, clean_text[index:].strip(), True

    def _strip_render_marker_prefix(self, text: str) -> str:
        clean_text = normalize_pdf_text(text)
        index = 0
        saw_prefix = False

        while index < len(clean_text):
            char = clean_text[index]
            if char.isspace() and saw_prefix:
                index += 1
                continue
            if char in {"\x00", "\ufffd", "\ufe0f", "\u200d"} or char in MARKER_GLYPHS or is_symbol_emoji(char):
                saw_prefix = True
                index += 1
                continue
            break

        return clean_text[index:].strip() if saw_prefix else clean_text

    def _span_preserved_visual_rects(self, span: Dict[str, Any]) -> List[fitz.Rect]:
        rects: List[fitz.Rect] = []
        for char_info in span.get("char_bboxes") or []:
            char = str(char_info.get("char") or "")
            if not char or char in {"\ufe0f", "\u200d"} or not is_symbol_emoji(char):
                continue
            bbox = char_info.get("bbox")
            if not bbox:
                continue
            try:
                char_rect = self._rect_from_bbox_mapping(bbox)
            except Exception:
                continue
            if not char_rect.is_empty:
                rects.append(char_rect)

        if rects:
            return rects

        span_text = normalize_pdf_text(span.get("text", ""))
        if not span_text or not is_symbol_emoji_text(span_text):
            return []

        bbox = span.get("bbox")
        if not bbox:
            return []
        try:
            span_rect = self._rect_from_bbox_mapping(bbox)
        except Exception:
            return []
        return [] if span_rect.is_empty else [span_rect]

    def _block_preserved_visual_rects(self, block: Dict[str, Any]) -> List[fitz.Rect]:
        rects: List[fitz.Rect] = []
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                rects.extend(self._span_preserved_visual_rects(span))
        return rects

    def _leading_preserved_visual_rects(
        self,
        block: Dict[str, Any],
        source_rect: fitz.Rect,
        font_size: float,
    ) -> List[fitz.Rect]:
        rects = self._block_preserved_visual_rects(block)
        if not rects or source_rect.is_empty:
            return []

        first_line_rect = None
        for line in block.get("lines", []):
            if not normalize_pdf_text(line.get("text", "")):
                continue
            bbox = line.get("bbox")
            if not bbox:
                continue
            try:
                first_line_rect = fitz.Rect(bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"])
            except Exception:
                first_line_rect = None
            break

        if first_line_rect is None or first_line_rect.is_empty:
            first_line_rect = source_rect

        _, _, has_visual_marker = self._split_preserved_visual_marker_prefix(block.get("text", ""))
        leading_band_width = (
            max(font_size * 4.5, 28.0)
            if has_visual_marker
            else max(font_size * 0.8, 8.0)
        )
        leading_limit = min(source_rect.x1, first_line_rect.x0 + leading_band_width)
        leading_rects: List[fitz.Rect] = []

        for rect in rects:
            if rect.is_empty:
                continue
            vertical_overlap = min(first_line_rect.y1, rect.y1) - max(first_line_rect.y0, rect.y0)
            min_height = max(min(first_line_rect.height, rect.height), 1.0)
            if vertical_overlap < min_height * 0.35:
                continue
            if rect.x0 > leading_limit:
                continue
            leading_rects.append(rect)

        return leading_rects

    def _iter_redaction_rects_for_blocks(self, blocks: List[Dict[str, Any]]) -> List[fitz.Rect]:
        rects: List[fitz.Rect] = []
        for block in blocks or []:
            block_rect = None
            try:
                bbox = block.get("bbox", {})
                block_rect = fitz.Rect(bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"])
            except Exception:
                block_rect = None

            initial_rect_count = len(rects)
            for line in block.get("lines", []):
                span_rects: List[fitz.Rect] = []

                for span in line.get("spans", []):
                    if not normalize_pdf_text(span.get("text", "")):
                        continue
                    for span_rect in self._span_text_rects_without_symbol_emoji(span):
                        span_rects.append(span_rect)

                merged_span_rects: List[fitz.Rect] = []
                for span_rect in sorted(span_rects, key=lambda rect: (rect.y0, rect.x0, rect.x1)):
                    if not merged_span_rects:
                        merged_span_rects.append(span_rect)
                        continue

                    previous_rect = merged_span_rects[-1]
                    vertical_overlap = min(previous_rect.y1, span_rect.y1) - max(previous_rect.y0, span_rect.y0)
                    min_height = max(min(previous_rect.height, span_rect.height), 1.0)
                    horizontal_gap = span_rect.x0 - previous_rect.x1
                    merge_gap = max(2.0, min(previous_rect.height, span_rect.height) * 0.25)
                    if vertical_overlap >= min_height * 0.55 and -1.0 <= horizontal_gap <= merge_gap:
                        merged_span_rects[-1] = previous_rect | span_rect
                    else:
                        merged_span_rects.append(span_rect)

                for redaction_rect in merged_span_rects:
                    inset_y = min(1.8, redaction_rect.height * 0.12)
                    inset_x = min(1.0, redaction_rect.width * 0.03)
                    page_height = float(block.get("page_height") or 0)
                    if page_height > 0 and redaction_rect.y0 <= page_height * 0.10:
                        inset_y = max(inset_y, min(3.0, redaction_rect.height * 0.20))
                    if redaction_rect.height > inset_y * 2 and redaction_rect.width > inset_x * 2:
                        redaction_rect = fitz.Rect(
                            redaction_rect.x0 + inset_x,
                            redaction_rect.y0 + inset_y,
                            redaction_rect.x1 - inset_x,
                            redaction_rect.y1 - inset_y,
                        )
                    rects.append(redaction_rect)
            if len(rects) == initial_rect_count and block_rect and not block_rect.is_empty:
                rects.append(block_rect)

        return rects

    def _insert_source_page_visual_layer(
        self,
        target_page,
        source_page,
        target_rect: fitz.Rect,
        scale: float = None,
        redact_blocks: List[Dict[str, Any]] = None,
    ):
        started_at = time.perf_counter()
        page_number = (source_page.number + 1) if source_page.number is not None else None
        redaction_rects = self._iter_redaction_rects_for_blocks(redact_blocks or [])
        redaction_count = len(redaction_rects)
        try:
            source_doc = source_page.parent
            if source_doc is None or source_page.number is None:
                raise ValueError("Source page has no parent document")

            temp_doc = fitz.open()
            try:
                temp_page = temp_doc.new_page(width=source_page.rect.width, height=source_page.rect.height)
                temp_page.show_pdf_page(temp_page.rect, source_doc, source_page.number)
                for rect in redaction_rects:
                    temp_page.add_redact_annot(rect, fill=fitz.utils.getColor("white"))

                if redaction_rects:
                    temp_page.apply_redactions(
                        images=fitz.PDF_REDACT_IMAGE_NONE,
                        graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                    )
                target_page.show_pdf_page(target_rect, temp_doc, 0)
                _pdf_perf_log(
                    "source_visual_layer",
                    page=page_number,
                    mode="vector",
                    redactions=redaction_count,
                    elapsed_ms=_elapsed_ms(started_at),
                )
                return
            finally:
                temp_doc.close()
        except Exception as e:
            print(f"[DEBUG] Failed to insert vector source visual layer: {str(e)}")

        try:
            # Keep the translation-side background crisp enough for reading while
            # avoiding the very large PDFs caused by 2x full-page rasterization.
            render_scale = scale or self.PREVIEW_VISUAL_LAYER_SCALE
            pixmap = source_page.get_pixmap(
                matrix=fitz.Matrix(render_scale, render_scale),
                alpha=False,
            )
            target_page.insert_image(target_rect, stream=pixmap_to_export_image_bytes(pixmap))
            _pdf_perf_log(
                "source_visual_layer",
                page=page_number,
                mode="raster",
                redactions=redaction_count,
                scale=render_scale,
                elapsed_ms=_elapsed_ms(started_at),
            )
            return
        except Exception as e:
            print(f"[DEBUG] Failed to insert source visual layer: {str(e)}")

        target_page.draw_rect(
            target_rect,
            color=fitz.utils.getColor("white"),
            fill=fitz.utils.getColor("white"),
        )
        _pdf_perf_log(
            "source_visual_layer",
            page=page_number,
            mode="blank",
            redactions=redaction_count,
            elapsed_ms=_elapsed_ms(started_at),
        )

    def _should_preserve_marker_span(self, span_text: str) -> bool:
        clean_text = normalize_pdf_text(span_text)
        if not clean_text:
            return True

        marker, heading_text, saw_marker = self._split_marker_prefix(clean_text)
        if saw_marker and marker and not heading_text:
            return True

        return clean_text in MARKER_GLYPHS

    def _cover_source_text_on_translation_side(
        self,
        target_page,
        block: Dict[str, Any],
        page_width: float,
        fallback_rect: fitz.Rect,
        fill_color,
        preserve_marker: bool = False,
    ):
        visible_lines = [
            line for line in block.get("lines", [])
            if normalize_pdf_text(line.get("text", ""))
        ]
        line_count = len(visible_lines)
        block_font_size = float(block.get("font_size") or 0)
        clean_text = normalize_pdf_text(block.get("text", ""))
        compact_heading = (
            line_count <= 1
            and len(clean_text) <= 40
            and block_font_size >= 18
        )
        span_rects = []
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if preserve_marker and self._should_preserve_marker_span(span.get("text", "")):
                    continue
                for span_rect in self._span_text_rects_without_symbol_emoji(span):
                    span_rects.append(span_rect)

        if not span_rects:
            span_rects = [fallback_rect]

        for span_rect in span_rects:
            vertical_padding = min(0.5, span_rect.height * (0.025 if compact_heading else 0.04))
            horizontal_padding = min(0.35, span_rect.width * 0.01)
            page_height = float(block.get("page_height") or 0)
            if page_height > 0 and span_rect.y0 <= page_height * 0.10:
                vertical_padding = max(vertical_padding, min(2.2, span_rect.height * 0.18))
            cover_rect = fitz.Rect(
                page_width + span_rect.x0 - horizontal_padding,
                span_rect.y0 + vertical_padding,
                page_width + span_rect.x1 + horizontal_padding,
                span_rect.y1 - vertical_padding,
            )
            if cover_rect.is_empty:
                continue

            target_page.draw_rect(
                cover_rect,
                color=fill_color,
                fill=fill_color,
                overlay=True,
            )

    def _translation_start_x(self, block: Dict[str, Any], source_rect: fitz.Rect, font_size: float) -> float:
        lines = [line for line in block.get("lines", []) if line.get("spans")]
        if not lines:
            return source_rect.x0

        top_y = min(line.get("bbox", {}).get("y0", source_rect.y0) for line in lines)
        spans = []
        for line in lines:
            line_bbox = line.get("bbox", {})
            if line_bbox.get("y0", source_rect.y0) > top_y + font_size * 0.35:
                continue
            for span in line.get("spans", []):
                text = normalize_pdf_text(span.get("text", ""))
                bbox = span.get("bbox")
                if not text or not bbox:
                    continue
                try:
                    spans.append((text, fitz.Rect(bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"])))
                except Exception:
                    continue

        spans.sort(key=lambda item: item[1].x0)
        for previous, current in zip(spans, spans[1:]):
            previous_text, previous_rect = previous
            _, current_rect = current
            gap = current_rect.x0 - previous_rect.x1
            previous_is_label = len(previous_text) <= 8 and previous_rect.width <= font_size * 3
            if previous_is_label and gap >= font_size * 0.9:
                return current_rect.x0

        return source_rect.x0

    def _compose_line_text_from_spans(self, line_spans: List[Dict[str, Any]]) -> str:
        parts: List[str] = []
        previous_rect = None
        previous_font_size = 0.0

        for span in line_spans:
            text = normalize_pdf_text(span.get("text", ""))
            if not text:
                continue
            is_reference_marker = bool(span.get("is_reference_marker"))

            bbox = span.get("bbox") or {}
            try:
                rect = fitz.Rect(bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"])
            except Exception:
                rect = None

            if not parts:
                parts.append(text)
                previous_rect = rect
                previous_font_size = float(span.get("font_size") or 0)
                continue

            previous_text = parts[-1]
            gap = 0.0
            if previous_rect is not None and rect is not None:
                gap = rect.x0 - previous_rect.x1
            font_size = max(previous_font_size, float(span.get("font_size") or 0), 1.0)
            tight_before = text[0] in ",.;:!?%)]}\u3001\u3002\uff0c\uff1b\uff1a\uff01\uff1f\uff09\uff3d\uff5d"
            math_symbols = "<>=\u2264\u2265\u2248\u223c~\u00d7\u00f7\u00b1"
            tight_after = previous_text[-1] in ("([{" + math_symbols + "\uff08\uff3b\uff5b")
            operator_number = previous_text[-1] in math_symbols and text[0].isdigit()
            symbol_prefix = text[0] in math_symbols and (not previous_text[-1].isalnum() or gap <= max(font_size * 0.35, 2.5))
            hyphenated = previous_text[-1] in "-\u2010\u2011\u2012\u2013" and text[0].isalnum()

            if is_reference_marker or tight_before or tight_after or operator_number or symbol_prefix or hyphenated:
                parts[-1] = f"{previous_text}{text}"
            else:
                parts.append(text)

            previous_rect = rect
            previous_font_size = float(span.get("font_size") or previous_font_size)

        return " ".join(parts).strip()

    def _looks_like_reference_marker_text(self, text: str, span_size: float) -> bool:
        return (
            len(text) <= 6
            and span_size <= 7.2
            and any(char.isdigit() for char in text)
            and bool(re.fullmatch(r"[\d,.\-\u2013\u2014]+", text))
        )

    def _looks_like_inline_reference_marker(
        self,
        text: str,
        span: Dict[str, Any],
        line_spans: List[Dict[str, Any]],
    ) -> bool:
        span_size = float(span.get("size") or 0)
        if not self._looks_like_reference_marker_text(text, span_size) or not line_spans:
            return False

        base_span = None
        for previous_span in reversed(line_spans):
            if not previous_span.get("is_reference_marker") and normalize_pdf_text(previous_span.get("text", "")):
                base_span = previous_span
                break
        if not base_span:
            return False

        base_font_size = float(base_span.get("font_size") or 0)
        if base_font_size <= 0 or span_size <= 0:
            return False
        if span_size > max(4.8, base_font_size * 0.88):
            return False

        try:
            span_rect = fitz.Rect(span["bbox"][0], span["bbox"][1], span["bbox"][2], span["bbox"][3])
            base_bbox = base_span.get("bbox") or {}
            base_rect = fitz.Rect(base_bbox["x0"], base_bbox["y0"], base_bbox["x1"], base_bbox["y1"])
        except Exception:
            return span_size <= base_font_size * 0.72

        vertical_lift = base_rect.y1 - span_rect.y1
        looks_raised = vertical_lift >= max(base_font_size * 0.16, 1.1)
        very_small = span_size <= base_font_size * 0.72
        return looks_raised or very_small

    def _format_reference_marker_text(self, text: str) -> str:
        superscript_digits = str.maketrans({
            "0": "\u2070",
            "1": "\u00b9",
            "2": "\u00b2",
            "3": "\u00b3",
            "4": "\u2074",
            "5": "\u2075",
            "6": "\u2076",
            "7": "\u2077",
            "8": "\u2078",
            "9": "\u2079",
        })
        return text.translate(superscript_digits)

    def _normalize_reference_markers_for_render(self, text: str) -> str:
        if not text:
            return text

        def replace_marker(match: re.Match[str]) -> str:
            return match.group(0).translate(REFERENCE_RENDER_TRANSLATION)

        return REFERENCE_RENDER_MARKER_RE.sub(replace_marker, text)

    def _span_text(self, span: Dict[str, Any]) -> str:
        explicit_text = span.get("text")
        if explicit_text is not None:
            return str(explicit_text)

        chars = span.get("chars") or []
        if not chars:
            return ""

        boundaries = []
        previous_char = None
        previous_bbox = None
        for char in chars:
            current = str(char.get("c", ""))
            bbox = char.get("bbox")
            if not current or bbox is None:
                continue
            if previous_char is not None and previous_bbox is not None:
                try:
                    gap = float(bbox[0]) - float(previous_bbox[2])
                    if self._char_gap_is_missing_space(previous_char, current, gap, float(span.get("size") or 0)):
                        boundaries.append(True)
                    else:
                        boundaries.append(False)
                except Exception:
                    boundaries.append(False)
            previous_char = current
            previous_bbox = bbox

        if boundaries and sum(1 for value in boundaries if value) / len(boundaries) > 0.45:
            boundaries = [False] * len(boundaries)

        parts: List[str] = []
        boundary_index = 0
        for char_index, char in enumerate(chars):
            current = str(char.get("c", ""))
            if not current:
                continue
            if char_index > 0:
                insert_space = boundaries[boundary_index] if boundary_index < len(boundaries) else False
                boundary_index += 1
                if insert_space and parts and not parts[-1].endswith(" "):
                    parts.append(" ")
            parts.append(current)

        return "".join(parts)

    def _char_gap_is_missing_space(self, previous_char: str, current_char: str, gap: float, font_size: float) -> bool:
        if gap < max(font_size * 0.105, 0.75):
            return False
        if previous_char.isspace() or current_char.isspace():
            return False
        if previous_char in "-\u2010\u2011\u2012\u2013/(" or current_char in ".,;:!?%)]}":
            return False
        math_symbols = "<>=\u2264\u2265\u2248\u223c~\u00d7\u00f7\u00b1"
        if previous_char in math_symbols or current_char in math_symbols:
            return False
        previous_is_word = previous_char.isalnum() or previous_char in "'\u2019"
        current_is_word = current_char.isalnum() or current_char in "'\u2019"
        return previous_is_word and current_is_word

    def _repair_symbol_span_text(
        self,
        text: str,
        span: Dict[str, Any],
        previous_text: str,
        next_span: Dict[str, Any],
    ) -> str:
        clean = normalize_pdf_text(text)
        next_text = normalize_pdf_text(self._span_text(next_span))
        if not clean or not next_text:
            return text

        current_font = str(span.get("font") or "")
        next_font = str(next_span.get("font") or "")
        if not current_font or current_font == next_font:
            return text

        previous = normalize_pdf_text(previous_text).lower()
        current_looks_symbolic = bool(re.search(r"(symbol|advp|math|mt|cmsy|cmex|glyph)", current_font, re.I))
        if not current_looks_symbolic:
            return text

        next_starts_number = bool(re.match(r"^\d", next_text))
        if clean == "5" and next_starts_number:
            return "="

        if clean == "3" and re.search(r"\d\s*$", previous):
            return "\u00d7"

        if clean == "." and next_starts_number:
            return ">"

        if clean != "," or not next_starts_number:
            return text

        if re.search(r"\b(frequency|rate|ratio|proportion|percent|percentage)\s*$", previous):
            return "<" if clean == "," else ">"

        return "~"

    def _source_first_line_indent(self, block: Dict[str, Any], source_rect: fitz.Rect, font_size: float) -> float:
        line_rects = []
        for line in block.get("lines", []):
            if not normalize_pdf_text(line.get("text", "")):
                continue
            bbox = line.get("bbox")
            if not bbox:
                continue
            try:
                line_rects.append(fitz.Rect(bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"]))
            except Exception:
                continue

        if len(line_rects) < 2:
            return 0.0

        first_line = line_rects[0]
        following_left = min(line.x0 for line in line_rects[1:])
        indent = first_line.x0 - following_left
        if indent >= max(font_size * 0.45, 4.0) and indent <= source_rect.width * 0.18:
            return indent
        return 0.0

    def _copy_source_marker(
        self,
        target_page,
        source_doc,
        page_num: int,
        source_rect: fitz.Rect,
        target_rect: fitz.Rect,
        font_size: float,
        max_source_x: float = None,
    ) -> float:
        if source_rect.is_empty or target_rect.is_empty:
            return 0

        clip_width = min(source_rect.width, max(font_size * 1.25, source_rect.height * 0.7))
        clip_x1 = min(source_rect.x1, source_rect.x0 + clip_width)
        if max_source_x is not None:
            clip_x1 = min(clip_x1, max_source_x)
        clip_rect = fitz.Rect(
            source_rect.x0,
            source_rect.y0,
            clip_x1,
            source_rect.y1,
        )
        if clip_rect.is_empty:
            return 0

        marker_height = min(target_rect.height, max(font_size * 1.2, 8))
        marker_width = min(
            target_rect.width,
            clip_rect.width * marker_height / max(clip_rect.height, 1),
        )
        if marker_width <= 0 or marker_height <= 0:
            return 0

        dest_rect = fitz.Rect(
            target_rect.x0,
            target_rect.y0,
            target_rect.x0 + marker_width,
            target_rect.y0 + marker_height,
        )
        try:
            pixmap = source_doc[page_num].get_pixmap(
                matrix=fitz.Matrix(3, 3),
                clip=clip_rect,
                alpha=True,
            )
            target_page.insert_image(dest_rect, stream=pixmap.tobytes("png"))
            return marker_width
        except Exception as e:
            print(f"[DEBUG] Failed to copy marker: {str(e)}")
            return 0

    def _find_inline_graphic_anchors(
        self,
        page,
        block: Dict[str, Any],
        source_rect: fitz.Rect,
        font_size: float,
    ) -> List[fitz.Rect]:
        lines = [
            line for line in block.get("lines", [])
            if normalize_pdf_text(line.get("text", ""))
        ]
        if not lines or source_rect.is_empty:
            return []

        first_line_bbox = lines[0].get("bbox")
        if not first_line_bbox:
            return []

        try:
            first_line_rect = fitz.Rect(
                first_line_bbox["x0"],
                first_line_bbox["y0"],
                first_line_bbox["x1"],
                first_line_bbox["y1"],
            )
        except Exception:
            return []

        if first_line_rect.is_empty:
            return []

        expanded_line_rect = fitz.Rect(
            source_rect.x0 - max(font_size * 1.2, 8.0),
            first_line_rect.y0 - max(font_size * 0.45, 4.0),
            source_rect.x1 + max(font_size * 1.2, 8.0),
            first_line_rect.y1 + max(font_size * 0.45, 4.0),
        )
        max_graphic_size = max(font_size * 3.8, 54.0)
        min_graphic_size = max(5.0, font_size * 0.35)
        anchors: List[fitz.Rect] = []

        for image_rect in self._get_page_image_rects(page):
            if image_rect.is_empty:
                continue
            if image_rect.width < min_graphic_size or image_rect.height < min_graphic_size:
                continue
            if image_rect.width > max_graphic_size or image_rect.height > max_graphic_size:
                continue
            if not expanded_line_rect.intersects(image_rect):
                continue

            center_x = image_rect.x0 + image_rect.width / 2
            if source_rect.x0 - max(font_size, 8.0) <= center_x <= source_rect.x1 + max(font_size, 8.0):
                anchors.append(image_rect)

        return anchors

    def _copy_source_graphic_anchors(
        self,
        target_page,
        source_page,
        source_rects: List[fitz.Rect],
        x_offset: float,
    ) -> None:
        for source_rect in source_rects:
            if source_rect.is_empty:
                continue

            dest_rect = fitz.Rect(
                x_offset + source_rect.x0,
                source_rect.y0,
                x_offset + source_rect.x1,
                source_rect.y1,
            )
            try:
                pixmap = source_page.get_pixmap(
                    matrix=fitz.Matrix(3, 3),
                    clip=source_rect,
                    alpha=True,
                )
                target_page.insert_image(dest_rect, stream=pixmap.tobytes("png"))
            except Exception as e:
                print(f"[DEBUG] Failed to copy inline graphic: {str(e)}")

    def _measure_text_width(self, text: str, font_size: float, measure_font=None, font_name: str = "helv") -> float:
        if not text:
            return 0
        text = self._normalize_reference_markers_for_render(text)
        if measure_font:
            return measure_font.text_length(text, fontsize=font_size)
        return fitz.get_text_length(text, fontname=font_name, fontsize=font_size)

    def _sanitize_text_for_render_font(self, text: str, measure_font=None) -> str:
        clean_text = sanitize_translated_text(text)
        if not clean_text or measure_font is None or not hasattr(measure_font, "has_glyph"):
            return clean_text

        filtered_chars: List[str] = []
        previous_was_space = False
        for char in clean_text:
            if char.isspace():
                if not previous_was_space:
                    filtered_chars.append(" ")
                previous_was_space = True
                continue

            try:
                has_glyph = bool(measure_font.has_glyph(ord(char)))
            except Exception:
                has_glyph = True
            if not has_glyph:
                continue

            filtered_chars.append(char)
            previous_was_space = False

        return normalize_pdf_text("".join(filtered_chars))

    def _insert_text_line_with_reference_markers(
        self,
        page,
        point,
        line: str,
        font_name: str,
        font_size: float,
        color,
        measure_font=None,
    ) -> None:
        x, baseline = point
        cursor = 0
        for match in REFERENCE_RENDER_MARKER_RE.finditer(line or ""):
            if match.start() > cursor:
                segment = self._normalize_reference_markers_for_render(line[cursor:match.start()])
                if segment:
                    page.insert_text(
                        (x, baseline),
                        segment,
                        fontsize=font_size,
                        fontname=font_name,
                        color=color,
                    )
                    x += self._measure_text_width(segment, font_size, measure_font, font_name)

            marker = match.group(0).translate(REFERENCE_RENDER_TRANSLATION)
            if marker:
                marker_size = max(font_size * 0.62, 3.8)
                marker_baseline = baseline - font_size * 0.34
                page.insert_text(
                    (x, marker_baseline),
                    marker,
                    fontsize=marker_size,
                    fontname=font_name,
                    color=color,
                )
                x += self._measure_text_width(marker, marker_size, measure_font, font_name)
            cursor = match.end()

        if cursor < len(line or ""):
            segment = self._normalize_reference_markers_for_render(line[cursor:])
            if segment:
                page.insert_text(
                    (x, baseline),
                    segment,
                    fontsize=font_size,
                    fontname=font_name,
                    color=color,
                )

    def _wrap_text_for_rect(
        self,
        text: str,
        max_width: float,
        font_size: float,
        measure_font=None,
        font_name: str = "helv",
        preserve_leading_space: bool = False,
        first_line_width: float = None,
    ) -> List[str]:
        wrapped_lines = []
        width_cache = {}
        no_line_start = set(",.;:!?%)]}，。！？；：、）》】”’」』）〉》〕］｝%")
        no_line_end = set("([{（《【“‘「『〈《〔［｛")

        def measure(value: str) -> float:
            cache_key = value
            if cache_key not in width_cache:
                width_cache[cache_key] = self._measure_text_width(value, font_size, measure_font, font_name)
            return width_cache[cache_key]

        def find_split_index(value: str, width: float) -> int:
            low = 1
            high = len(value)
            best = 1
            while low <= high:
                mid = (low + high) // 2
                if measure(value[:mid]) <= width:
                    best = mid
                    low = mid + 1
                else:
                    high = mid - 1
            return max(best, 1)

        for paragraph in normalize_pdf_text(text, preserve_leading_space=preserve_leading_space).splitlines():
            tokens = []
            current_word = ""

            for char in paragraph:
                is_cjk = '\u4e00' <= char <= '\u9fff'
                is_cjk_punctuation = char in CJK_PUNCTUATION
                if char.isspace():
                    if current_word:
                        tokens.append(current_word)
                        current_word = ""
                    tokens.append(" ")
                elif is_cjk or is_cjk_punctuation:
                    if current_word:
                        tokens.append(current_word)
                        current_word = ""
                    tokens.append(char)
                else:
                    current_word += char

            if current_word:
                tokens.append(current_word)

            line = ""
            for token in tokens:
                if token == " " and not line:
                    continue

                candidate = f"{line}{token}" if line else (token if preserve_leading_space else token.strip())
                allowed_width = first_line_width if not wrapped_lines and first_line_width else max_width
                if measure(candidate) <= allowed_width:
                    line = candidate
                    continue

                if line:
                    wrapped_lines.append(line.rstrip())
                    line = token if preserve_leading_space else token.strip()

                while (
                    line
                    and measure(line) > (first_line_width if not wrapped_lines and first_line_width else max_width)
                    and len(line) > 1
                ):
                    split_width = first_line_width if not wrapped_lines and first_line_width else max_width
                    split_index = find_split_index(line, split_width)
                    wrapped_lines.append(line[:split_index].rstrip())
                    line = line[split_index:] if preserve_leading_space else line[split_index:].lstrip()

            if line:
                wrapped_lines.append(line.rstrip())

        if len(wrapped_lines) <= 1:
            return wrapped_lines

        rebalanced_lines = [line for line in wrapped_lines if line]
        index = 1
        while index < len(rebalanced_lines):
            current_line = rebalanced_lines[index]
            previous_line = rebalanced_lines[index - 1]
            if current_line and current_line[0] in no_line_start and previous_line:
                allowed_width = first_line_width if index - 1 == 0 and first_line_width else max_width
                candidate = f"{previous_line}{current_line[0]}"
                if measure(candidate) <= allowed_width * 1.04:
                    rebalanced_lines[index - 1] = candidate
                    rebalanced_lines[index] = current_line[1:].lstrip()
            if rebalanced_lines[index - 1] and rebalanced_lines[index - 1][-1] in no_line_end:
                rebalanced_lines[index] = f"{rebalanced_lines[index - 1][-1]}{rebalanced_lines[index]}"
                rebalanced_lines[index - 1] = rebalanced_lines[index - 1][:-1].rstrip()
            if not rebalanced_lines[index - 1]:
                del rebalanced_lines[index - 1]
                index = max(index - 1, 1)
                continue
            if not rebalanced_lines[index]:
                del rebalanced_lines[index]
                continue
            index += 1

        return rebalanced_lines

    def _insert_fitted_textbox(
        self,
        page,
        rect: fitz.Rect,
        text: str,
        font_name: str,
        font_size: float,
        color,
        align=fitz.TEXT_ALIGN_LEFT,
        min_font_size: float = 5.5,
        line_height: float = 1.28,
        measure_font=None,
        vertical_align: str = "top",
        force_manual_wrap: bool = False,
        first_line_indent: float = 0.0,
    ) -> bool:
        leading_ideographic_spaces = "\u3000" * (len(text or "") - len((text or "").lstrip("\u3000")))
        clean_text = self._sanitize_text_for_render_font(text, measure_font)
        if leading_ideographic_spaces and clean_text:
            clean_text = f"{leading_ideographic_spaces}{clean_text}"
        if not clean_text or rect.width <= 0 or rect.height <= 0:
            return False

        contains_reference_markers = bool(REFERENCE_RENDER_MARKER_RE.search(clean_text))
        current_size = max(font_size, min_font_size)
        first_line_indent = max(float(first_line_indent or 0.0), 0.0)
        if align != fitz.TEXT_ALIGN_LEFT:
            first_line_indent = 0.0
        first_line_indent = min(first_line_indent, max(rect.width - font_size * 2.0, 0.0))

        if vertical_align == "top" and not force_manual_wrap and first_line_indent <= 0 and not contains_reference_markers:
            while current_size >= min_font_size:
                try:
                    remaining = page.insert_textbox(
                        rect,
                        clean_text,
                        fontsize=current_size,
                        lineheight=line_height,
                        fontname=font_name,
                        color=color,
                        align=align,
                    )
                    if remaining >= 0:
                        return True
                except Exception:
                    break
                current_size *= 0.9
            return False

        current_size = max(font_size, min_font_size)
        while current_size >= min_font_size:
            lines = self._wrap_text_for_rect(
                clean_text,
                rect.width,
                current_size,
                measure_font=measure_font,
                font_name=font_name,
                preserve_leading_space=bool(leading_ideographic_spaces),
                first_line_width=(rect.width - first_line_indent) if first_line_indent > 0 else None,
            )
            line_step = current_size * line_height
            required_height = current_size + max(len(lines) - 1, 0) * line_step

            if lines and required_height <= rect.height:
                top_offset = 0
                if vertical_align == "middle":
                    top_offset = max((rect.height - required_height) / 2, 0)
                baseline = rect.y0 + top_offset + current_size

                if align == fitz.TEXT_ALIGN_LEFT:
                    if first_line_indent > 0:
                        for line_index, line in enumerate(lines):
                            text_x = rect.x0 + first_line_indent if line_index == 0 else rect.x0
                            self._insert_text_line_with_reference_markers(
                                page,
                                (text_x, baseline),
                                line,
                                font_name,
                                current_size,
                                color,
                                measure_font,
                            )
                            baseline += line_step
                    elif contains_reference_markers:
                        for line in lines:
                            self._insert_text_line_with_reference_markers(
                                page,
                                (rect.x0, baseline),
                                line,
                                font_name,
                                current_size,
                                color,
                                measure_font,
                            )
                            baseline += line_step
                    else:
                        page.insert_text(
                            (rect.x0, baseline),
                            lines,
                            fontsize=current_size,
                            lineheight=line_height,
                            fontname=font_name,
                            color=color,
                        )
                    return True

                for line in lines:
                    line_width = self._measure_text_width(line, current_size, measure_font, font_name)
                    text_x = rect.x0
                    if align == fitz.TEXT_ALIGN_CENTER:
                        text_x = rect.x0 + max(rect.width - line_width, 0) / 2
                    elif align == fitz.TEXT_ALIGN_RIGHT:
                        text_x = rect.x1 - line_width
                    text_x = max(rect.x0, min(text_x, rect.x1))
                    self._insert_text_line_with_reference_markers(
                        page,
                        (text_x, baseline),
                        line,
                        font_name,
                        current_size,
                        color,
                        measure_font,
                    )
                    baseline += line_step
                return True

            current_size *= 0.9

        return False

    def _translated_textbox_required_height(
        self,
        text: str,
        rect: fitz.Rect,
        font_name: str,
        font_size: float,
        line_height: float,
        measure_font=None,
        first_line_indent: float = 0.0,
    ) -> float:
        leading_ideographic_spaces = "\u3000" * (len(text or "") - len((text or "").lstrip("\u3000")))
        clean_text = self._sanitize_text_for_render_font(text, measure_font)
        if leading_ideographic_spaces and clean_text:
            clean_text = f"{leading_ideographic_spaces}{clean_text}"
        if not clean_text or rect.width <= 0 or rect.height <= 0 or font_size <= 0:
            return 0.0

        first_line_indent = max(float(first_line_indent or 0.0), 0.0)
        first_line_indent = min(first_line_indent, max(rect.width - font_size * 2.0, 0.0))
        lines = self._wrap_text_for_rect(
            clean_text,
            rect.width,
            font_size,
            measure_font=measure_font,
            font_name=font_name,
            preserve_leading_space=bool(leading_ideographic_spaces),
            first_line_width=(rect.width - first_line_indent) if first_line_indent > 0 else None,
        )
        if not lines:
            return 0.0
        return font_size + max(len(lines) - 1, 0) * font_size * line_height

    def _translated_text_fits_rect(
        self,
        text: str,
        rect: fitz.Rect,
        font_name: str,
        font_size: float,
        line_height: float,
        measure_font=None,
        first_line_indent: float = 0.0,
    ) -> bool:
        required_height = self._translated_textbox_required_height(
            text,
            rect,
            font_name,
            font_size,
            line_height,
            measure_font=measure_font,
            first_line_indent=first_line_indent,
        )
        return required_height > 0 and required_height <= rect.height

    def _find_textbox_fit_scale(
        self,
        text: str,
        rect: fitz.Rect,
        font_name: str,
        font_size: float,
        line_height: float,
        measure_font=None,
        first_line_indent: float = 0.0,
    ) -> float:
        if rect.width <= 0 or rect.height <= 0 or font_size <= 0 or not normalize_pdf_text(text):
            return 1.0
        if self._translated_text_fits_rect(
            text,
            rect,
            font_name,
            font_size,
            line_height,
            measure_font=measure_font,
            first_line_indent=first_line_indent,
        ):
            return 1.0

        low = 0.05
        high = 1.0
        for _ in range(10):
            midpoint = (low + high) / 2
            if self._translated_text_fits_rect(
                text,
                rect,
                font_name,
                font_size * midpoint,
                line_height,
                measure_font=measure_font,
                first_line_indent=first_line_indent * midpoint,
            ):
                low = midpoint
            else:
                high = midpoint
        return low

    def _insert_rotated_fitted_textbox(
        self,
        page,
        rect: fitz.Rect,
        text: str,
        font_name: str,
        font_size: float,
        color,
        min_font_size: float = 5.0,
    ) -> bool:
        leading_ideographic_spaces = "\u3000" * (len(text) - len(text.lstrip("\u3000")))
        clean_text = self._sanitize_text_for_render_font(text)
        if leading_ideographic_spaces and clean_text:
            clean_text = f"{leading_ideographic_spaces}{clean_text}"
        if not clean_text or rect.width <= 0 or rect.height <= 0:
            return False

        current_size = max(font_size, min_font_size)
        while current_size >= min_font_size:
            try:
                remaining = page.insert_textbox(
                    rect,
                    clean_text,
                    fontsize=current_size,
                    fontname=font_name,
                    color=color,
                    align=fitz.TEXT_ALIGN_CENTER,
                    rotate=90,
                )
                if remaining >= 0:
                    return True
            except Exception:
                return False
            current_size *= 0.9

        return False

    def _register_translation_fonts(self, page, regular_font_path: str, bold_font_path: str):
        started_at = time.perf_counter()
        regular_font_registered = False
        if regular_font_path:
            try:
                page.insert_font(fontfile=regular_font_path, fontname="custom_translation_regular")
                regular_font_registered = True
            except Exception as e:
                raise TranslationFontConfigurationError(
                    f"Failed to register PDF translation font: {regular_font_path}. Error: {e}"
                ) from e

        bold_font_registered = False
        if bold_font_path:
            try:
                page.insert_font(fontfile=bold_font_path, fontname="custom_translation_bold")
                bold_font_registered = True
            except Exception as e:
                raise TranslationFontConfigurationError(
                    f"Failed to register bold PDF translation font: {bold_font_path}. Error: {e}"
                ) from e

        regular_font_name = "custom_translation_regular" if regular_font_registered else "helv"
        bold_font_name = "custom_translation_bold" if bold_font_registered else regular_font_name
        try:
            regular_measure_font = (
                fitz.Font(fontfile=regular_font_path)
                if regular_font_registered
                else fitz.Font("helv")
            )
        except Exception:
            regular_measure_font = fitz.Font("helv")
        try:
            bold_measure_font = (
                fitz.Font(fontfile=bold_font_path)
                if bold_font_registered
                else regular_measure_font
            )
        except Exception:
            bold_measure_font = regular_measure_font

        _pdf_perf_log(
            "fonts_registered",
            page=(page.number + 1) if page.number is not None else None,
            regular=bool(regular_font_path),
            bold=bool(bold_font_path),
            regular_registered=regular_font_registered,
            bold_registered=bold_font_registered,
            elapsed_ms=_elapsed_ms(started_at),
        )
        return regular_font_name, bold_font_name, regular_measure_font, bold_measure_font

    def _block_visible_line_count(self, block: Dict[str, Any]) -> int:
        return len([
            line for line in block.get("lines", [])
            if normalize_pdf_text(line.get("text", ""))
        ])

    def _block_contains_symbol_emoji(self, block: Dict[str, Any]) -> bool:
        source_text = normalize_pdf_text(block.get("text", ""))
        if any(
            char not in {"\ufe0f", "\u200d"} and is_symbol_emoji(char)
            for char in source_text
        ):
            return True

        for line in block.get("lines", []):
            for span in line.get("spans", []):
                span_text = normalize_pdf_text(span.get("text", ""))
                if any(
                    char not in {"\ufe0f", "\u200d"} and is_symbol_emoji(char)
                    for char in span_text
                ):
                    return True
        return False

    def _is_compact_heading_translation_block(self, block: Dict[str, Any]) -> bool:
        if block.get("layout_role", "body") != "body":
            return False

        source_text = normalize_pdf_text(block.get("text", ""))
        if not source_text:
            return False

        line_count = self._block_visible_line_count(block)
        font_size = float(block.get("font_size") or 0)
        compact_len = len(re.sub(r"\s+", "", source_text))
        if line_count > 2 or font_size < 14 or compact_len > 90:
            return False

        if self._block_contains_symbol_emoji(block):
            return True

        word_count = len(re.findall(r"[\w\u4e00-\u9fff]+", source_text, flags=re.UNICODE))
        return (
            font_size >= 16
            and word_count <= 10
            and not source_text.rstrip().endswith(SENTENCE_ENDINGS)
        )

    def _is_main_body_translation_block(self, block: Dict[str, Any]) -> bool:
        return (
            block.get("layout_role", "body") == "body"
            and not self._is_compact_heading_translation_block(block)
        )

    def _line_height_for_translated_text(self, text: str, layout_role: str) -> float:
        line_height = 1.42 if has_cjk(text) and len(text) > 80 else 1.36 if has_cjk(text) else 1.2
        if layout_role == "marginalia":
            line_height = min(line_height, 1.16)
        return line_height

    def _main_body_text_rect_for_scale(
        self,
        block: Dict[str, Any],
        source_rect: fitz.Rect,
        original_rect: fitz.Rect,
        x_offset: float,
        target_right_edge: float,
        base_font_size: float,
        source_line_count: int,
        source_text: str,
        marker: str,
        first_line_indent: float,
    ) -> fitz.Rect:
        use_label_start_x = (
            not marker
            and source_line_count <= 2
            and len(source_text) <= 90
        )
        translation_start_x = (
            source_rect.x0
            if marker or not use_label_start_x
            else self._translation_start_x(block, source_rect, base_font_size)
        )
        target_rect = fitz.Rect(
            x_offset + translation_start_x,
            max(0, source_rect.y0 - 1),
            min(target_right_edge - 24, x_offset + source_rect.x1 + 2),
            min(original_rect.height - 12, source_rect.y1 + 1),
        )
        if target_rect.width < base_font_size * 2:
            target_rect.x1 = min(target_right_edge - 24, target_rect.x0 + base_font_size * 4)

        if marker:
            marker_width = base_font_size * 1.6
            target_rect = fitz.Rect(
                min(target_rect.x1, target_rect.x0 + marker_width),
                target_rect.y0,
                target_rect.x1,
                target_rect.y1,
            )
        return target_rect

    def _calculate_main_body_page_scale(
        self,
        text_blocks: List[Dict[str, Any]],
        src_page,
        original_rect: fitz.Rect,
        x_offset: float,
        target_right_edge: float,
        regular_font_name: str,
        bold_font_name: str,
        regular_measure_font,
        bold_measure_font,
    ) -> float:
        scale = 1.0
        measured_blocks = 0

        for block in text_blocks:
            if not self._is_main_body_translation_block(block):
                continue

            bbox = block.get("bbox", {})
            try:
                source_rect = fitz.Rect(bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"])
            except Exception:
                continue
            if source_rect.is_empty or source_rect.width <= 0 or source_rect.height <= 0:
                continue

            source_line_count = len([
                line for line in block.get("lines", [])
                if normalize_pdf_text(line.get("text", ""))
            ])
            translated_text = normalize_pdf_text(block.get("translatedText", ""))
            source_text = normalize_pdf_text(block.get("text", ""))
            marker, content_text = self._split_leading_marker(translated_text, source_text)
            if not content_text:
                content_text = translated_text
            if not content_text:
                continue
            source_compact_len = len(re.sub(r"\s+", "", source_text))
            content_compact_len = len(re.sub(r"\s+", "", content_text))
            if source_compact_len > 0 and content_compact_len <= source_compact_len * 1.04:
                continue

            style = self._get_block_style(src_page, source_rect, block.get("font_size") or 10, block)
            text_font_name = bold_font_name if style["is_bold"] else regular_font_name
            text_measure_font = bold_measure_font if style["is_bold"] else regular_measure_font
            base_font_size = float(block.get("font_size") or style["font_size"])
            if has_cjk(content_text):
                base_font_size *= 0.86
            if marker:
                base_font_size = max(base_font_size, style["font_size"] * 0.9)
            base_font_size = max(min(base_font_size, source_rect.height * 0.95), 0.5)
            first_line_indent = self._source_first_line_indent(block, source_rect, base_font_size)
            text_rect = self._main_body_text_rect_for_scale(
                block,
                source_rect,
                original_rect,
                x_offset,
                target_right_edge,
                base_font_size,
                source_line_count,
                source_text,
                marker,
                first_line_indent,
            )
            block_scale = self._find_textbox_fit_scale(
                content_text,
                text_rect,
                text_font_name,
                base_font_size,
                self._line_height_for_translated_text(content_text, "body"),
                measure_font=text_measure_font,
                first_line_indent=first_line_indent,
            )
            scale = min(scale, block_scale)
            measured_blocks += 1

        if measured_blocks <= 0:
            return 1.0
        return max(min(scale, 1.0), 0.05)

    def _add_bilingual_page(
        self,
        doc,
        src_doc,
        page_data: Dict[str, Any],
        regular_font_path: str,
        bold_font_path: str,
        *,
        visual_layer_scale: float = None,
    ):
        started_at = time.perf_counter()
        page_num = page_data["pageNum"] - 1
        if page_num < 0 or page_num >= len(src_doc):
            return None

        src_page = src_doc[page_num]
        original_rect = src_page.rect
        page_width = original_rect.width

        new_page = doc.new_page(width=original_rect.width * 2, height=original_rect.height)
        new_page.show_pdf_page(fitz.Rect(0, 0, page_width, original_rect.height), src_doc, page_num)

        right_bg_rect = fitz.Rect(page_width, 0, page_width * 2, original_rect.height)
        self._insert_source_page_visual_layer(
            new_page,
            src_page,
            right_bg_rect,
            scale=visual_layer_scale,
            redact_blocks=self._get_translated_text_blocks(page_data),
        )
        new_page.draw_line(
            (page_width, 0),
            (page_width, original_rect.height),
            color=fitz.utils.getColor("gray"),
            width=1.0,
        )

        required_scripts = detect_page_required_scripts(page_data)
        page_regular_font_path, page_bold_font_path = resolve_translation_font_paths(required_scripts)
        regular_font_path = page_regular_font_path or regular_font_path
        bold_font_path = page_bold_font_path or bold_font_path
        (
            regular_font_name,
            bold_font_name,
            regular_measure_font,
            bold_measure_font,
        ) = self._register_translation_fonts(
            new_page,
            regular_font_path,
            bold_font_path,
        )

        self._render_translated_text_blocks(
            new_page,
            src_page,
            page_data,
            original_rect,
            page_width,
            page_width * 2,
            regular_font_name,
            bold_font_name,
            regular_measure_font,
            bold_measure_font,
        )
        self._copy_source_block_regions(
            new_page,
            src_page,
            self._get_preserved_attribution_metadata_blocks(page_data),
            page_width,
        )
        _pdf_perf_log(
            "bilingual_page_rendered",
            page=page_data.get("pageNum"),
            blocks=len(self._get_translated_text_blocks(page_data)),
            elapsed_ms=_elapsed_ms(started_at),
        )
        return new_page

    def generate_bilingual_page_preview_png(
        self,
        file_id: str,
        translation_result: Dict[str, Any],
        page_num: int = 0,
        max_width: int = 1800,
    ) -> bytes:
        input_path = self.get_file_path(file_id)
        if not os.path.exists(input_path):
            raise FileNotFoundError("File not found")

        page_data_by_index = {
            int(page_data.get("pageNum", 0)) - 1: page_data
            for page_data in translation_result.get("pages", [])
            if page_data.get("pageNum")
        }
        page_data = page_data_by_index.get(page_num)
        if page_data is None:
            raise ValueError("Page has not been translated")

        src_doc = fitz.open(input_path)
        doc = fitz.open()
        try:
            self._clear_render_caches()
            preview_page = self._add_bilingual_page(
                doc,
                src_doc,
                page_data,
                "",
                "",
                visual_layer_scale=0.9,
            )
            if preview_page is None:
                raise ValueError("Invalid page number")

            page_width = max(float(preview_page.rect.width), 1.0)
            target_width = max(int(max_width), 600)
            zoom = min(target_width / page_width, 2.0)
            pixmap = preview_page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            return pixmap.tobytes("png")
        finally:
            self._clear_render_caches()
            doc.close()
            src_doc.close()

    def _get_translated_text_blocks(self, page_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        text_blocks = [
            block for block in page_data.get("textBlocks", [])
            if block.get("type") == "text"
            and block.get("translatedText")
            and not block.get("is_formula")
            and not block.get("is_header_footer_metadata")
            and self.is_translatable_text_block(block)
        ]
        return self._merge_text_blocks(text_blocks)

    def _get_preserved_attribution_metadata_blocks(self, page_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        if int(page_data.get("pageNum") or 0) != 1:
            return []
        return [
            block for block in page_data.get("textBlocks", [])
            if block.get("type") == "text"
            and block.get("is_attribution_metadata")
        ]

    def _copy_source_block_regions(
        self,
        target_page,
        source_page,
        blocks: List[Dict[str, Any]],
        x_offset: float,
    ) -> None:
        source_rects: List[fitz.Rect] = []
        for block in blocks:
            bbox = block.get("bbox", {})
            try:
                source_rect = fitz.Rect(bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"])
            except Exception:
                continue
            if source_rect.is_empty:
                continue
            source_rects.append(source_rect)

        if not source_rects:
            return

        clip_rect = fitz.Rect(source_rects[0])
        for source_rect in source_rects[1:]:
            clip_rect |= source_rect
        clip_rect.x0 = max(source_page.rect.x0, clip_rect.x0 - 14)
        clip_rect.y0 = max(source_page.rect.y0, clip_rect.y0 - 8)
        clip_rect.x1 = min(source_page.rect.x1, clip_rect.x1 + 14)
        clip_rect.y1 = min(source_page.rect.y1, clip_rect.y1 + 8)
        if clip_rect.is_empty:
            return

        dest_rect = fitz.Rect(
            x_offset + clip_rect.x0,
            clip_rect.y0,
            x_offset + clip_rect.x1,
            clip_rect.y1,
        )
        try:
            pixmap = source_page.get_pixmap(
                matrix=fitz.Matrix(3, 3),
                clip=clip_rect,
                alpha=True,
            )
            target_page.insert_image(dest_rect, stream=pixmap.tobytes("png"))
        except Exception as e:
            print(f"[DEBUG] Failed to copy preserved source block: {str(e)}")

    def _render_translated_text_blocks(
        self,
        target_page,
        src_page,
        page_data: Dict[str, Any],
        original_rect: fitz.Rect,
        x_offset: float,
        target_right_edge: float,
        regular_font_name: str,
        bold_font_name: str,
        regular_measure_font,
        bold_measure_font,
    ):
        started_at = time.perf_counter()
        text_blocks = self._get_translated_text_blocks(page_data)
        page_has_columns = any(
            block.get("layout_column") not in (None, -1)
            for block in text_blocks
        )
        main_body_page_scale = self._calculate_main_body_page_scale(
            text_blocks,
            src_page,
            original_rect,
            x_offset,
            target_right_edge,
            regular_font_name,
            bold_font_name,
            regular_measure_font,
            bold_measure_font,
        )
        rendered_count = 0
        failed_count = 0
        fallback_count = 0
        vertical_count = 0
        marginalia_count = 0

        for index, block in enumerate(text_blocks):
            bbox = block.get("bbox", {})
            try:
                source_rect = fitz.Rect(bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"])
            except Exception:
                continue

            if source_rect.is_empty or source_rect.width <= 0 or source_rect.height <= 0:
                continue

            source_line_count = len([
                line for line in block.get("lines", [])
                if normalize_pdf_text(line.get("text", ""))
            ])
            translated_text = normalize_pdf_text(block.get("translatedText", ""))
            source_text = normalize_pdf_text(block.get("text", ""))
            marker, content_text = self._split_leading_marker(translated_text, source_text)
            if not content_text:
                content_text = translated_text

            is_main_body_block = self._is_main_body_translation_block(block)
            is_compact_heading_block = self._is_compact_heading_translation_block(block)
            style = self._get_block_style(src_page, source_rect, block.get("font_size") or 10, block)
            text_font_name = bold_font_name if style["is_bold"] else regular_font_name
            text_measure_font = bold_measure_font if style["is_bold"] else regular_measure_font
            base_font_size = float(block.get("font_size") or style["font_size"])
            if has_cjk(content_text):
                base_font_size *= 0.86
            if marker:
                base_font_size = max(base_font_size, style["font_size"] * 0.9)
            base_font_size *= main_body_page_scale if is_main_body_block else 1.0
            base_font_size = max(min(base_font_size, source_rect.height * 0.95), 0.5 if is_main_body_block else 5.5)
            layout_role = block.get("layout_role", "body")
            first_line_indent = 0.0
            if layout_role == "body" and not marker:
                first_line_indent = self._source_first_line_indent(block, source_rect, base_font_size)

            bottom_limit = original_rect.height - 18
            for next_block in text_blocks[index + 1:]:
                next_bbox = next_block.get("bbox", {})
                next_y0 = next_bbox.get("y0")
                if next_y0 is None or next_y0 <= source_rect.y0 + 1:
                    continue
                horizontally_related = (
                    next_bbox.get("x1", 0) >= source_rect.x0 - 12 and
                    next_bbox.get("x0", 0) <= source_rect.x1 + 12
                )
                same_column = abs(next_bbox.get("x0", source_rect.x0) - source_rect.x0) < 80
                if horizontally_related or same_column:
                    bottom_limit = min(bottom_limit, next_y0 - 4)
                    break

            min_height = base_font_size * 1.35
            source_height = max(source_rect.height, min_height)
            text_length_ratio = len(content_text) / max(len(source_text), 1)
            expansion_factor = 1.0
            if has_cjk(content_text) and layout_role == "body" and not is_main_body_block:
                expansion_factor = 1.22 if text_length_ratio > 0.85 else 1.12
                if len(content_text) > 180:
                    expansion_factor += 0.12
            if is_main_body_block:
                target_bottom = min(original_rect.height - 12, source_rect.y1 + 1)
            else:
                target_bottom = min(
                    original_rect.height - 12,
                    max(
                        min(bottom_limit, source_rect.y0 + source_height * expansion_factor),
                        source_rect.y1 + 2,
                        source_rect.y0 + min_height,
                    ),
                )
            use_label_start_x = (
                not marker
                and source_line_count <= 2
                and len(source_text) <= 90
            )
            translation_start_x = (
                source_rect.x0
                if marker or not use_label_start_x
                else self._translation_start_x(block, source_rect, base_font_size)
            )

            target_rect = fitz.Rect(
                x_offset + translation_start_x,
                max(0, source_rect.y0 - 1),
                min(target_right_edge - 24, x_offset + source_rect.x1 + 2),
                min(original_rect.height - 12, target_bottom),
            )
            if is_compact_heading_block:
                try:
                    measured_heading_width = self._measure_text_width(
                        content_text,
                        base_font_size,
                        text_measure_font,
                        text_font_name,
                    )
                except Exception:
                    measured_heading_width = 0.0
                heading_width_cap = original_rect.width * (
                    0.42
                    if page_has_columns or block.get("layout_column") not in (None, -1)
                    else 0.72
                )
                heading_width = min(
                    max(
                        source_rect.width * 2.2,
                        base_font_size * 8.0,
                        measured_heading_width * 1.08,
                    ),
                    heading_width_cap,
                )
                target_rect.x1 = min(
                    target_right_edge - 24,
                    max(target_rect.x1, target_rect.x0 + heading_width),
                )
            if target_rect.width < base_font_size * 2:
                target_rect.x1 = min(target_right_edge - 24, target_rect.x0 + base_font_size * 4)

            leading_preserved_visual_rects = self._leading_preserved_visual_rects(
                block,
                source_rect,
                base_font_size,
            )
            if leading_preserved_visual_rects and not marker:
                preserved_right = max(rect.x1 for rect in leading_preserved_visual_rects)
                adjusted_x0 = x_offset + preserved_right + max(base_font_size * 0.25, 3.0)
                if adjusted_x0 <= target_rect.x1 - max(base_font_size * 3.0, 24.0):
                    target_rect.x0 = max(target_rect.x0, adjusted_x0)

            inline_graphic_anchors = []
            if (
                not marker
                and source_line_count <= 2
                and len(source_text) <= 180
                and not self._block_contains_symbol_emoji(block)
            ):
                inline_graphic_anchors = self._find_inline_graphic_anchors(
                    src_page,
                    block,
                    source_rect,
                    base_font_size,
                )
                leading_graphics = [
                    rect for rect in inline_graphic_anchors
                    if rect.x0 <= source_rect.x0 + source_rect.width * 0.55
                ]
                if leading_graphics:
                    graphic_right = max(rect.x1 for rect in leading_graphics)
                    adjusted_x0 = x_offset + graphic_right + max(base_font_size * 0.25, 3.0)
                    if adjusted_x0 <= target_rect.x1 - max(base_font_size * 3.0, 24.0):
                        target_rect.x0 = max(target_rect.x0, adjusted_x0)

            self._cover_source_text_on_translation_side(
                target_page,
                block,
                x_offset,
                source_rect,
                style["background_color"],
                preserve_marker=bool(marker),
            )

            text_rect = target_rect
            if marker:
                copied_marker_width = 0.0
                marker_copy_max_source_x = None
                preserved_marker_width = 0.0
                if leading_preserved_visual_rects:
                    first_preserved_left = min(rect.x0 for rect in leading_preserved_visual_rects)
                    marker_copy_max_source_x = first_preserved_left - max(base_font_size * 0.12, 1.0)
                    preserved_marker_width = max(
                        max(rect.x1 - source_rect.x0, 0.0)
                        for rect in leading_preserved_visual_rects
                    )
                source_doc = getattr(src_page, "parent", None)
                source_page_number = getattr(src_page, "number", None)
                if source_doc is not None and source_page_number is not None:
                    copied_marker_width = self._copy_source_marker(
                        target_page,
                        source_doc,
                        source_page_number,
                        source_rect,
                        target_rect,
                        base_font_size,
                        max_source_x=marker_copy_max_source_x,
                    )
                marker_gap = max(base_font_size * 0.25, 2.0)
                marker_width = max(
                    copied_marker_width + marker_gap,
                    preserved_marker_width + marker_gap,
                    base_font_size * 1.35,
                )
                text_rect = fitz.Rect(
                    min(target_rect.x1, target_rect.x0 + marker_width),
                    target_rect.y0,
                    target_rect.x1,
                    target_rect.y1,
                )

            try:
                if layout_role == "vertical_text":
                    vertical_count += 1
                elif layout_role == "marginalia":
                    marginalia_count += 1

                if layout_role == "vertical_text":
                    success = self._insert_rotated_fitted_textbox(
                        target_page,
                        text_rect,
                        content_text,
                        text_font_name,
                        min(base_font_size, max(text_rect.width, text_rect.height) * 0.18),
                        style["color"],
                        min_font_size=max(4.8, base_font_size * 0.52),
                        )
                    if not success:
                        fallback_count += 1
                        self._insert_fitted_textbox(
                            target_page,
                            text_rect,
                            content_text,
                            text_font_name,
                            min(base_font_size, 8.0),
                            style["color"],
                            align=fitz.TEXT_ALIGN_CENTER,
                            min_font_size=4.8,
                            line_height=1.12,
                            measure_font=text_measure_font,
                            vertical_align="middle",
                            force_manual_wrap=has_cjk(content_text),
                        )
                    rendered_count += 1
                    continue

                line_height = self._line_height_for_translated_text(content_text, layout_role)
                text_align = fitz.TEXT_ALIGN_LEFT if marker else style["align"]
                vertical_align = (
                    "middle"
                    if (
                        source_line_count == 1
                        and len(content_text) <= 40
                        and base_font_size <= 42
                        and source_rect.height >= base_font_size * 1.8
                    )
                    else "top"
                )
                min_readable_size = (
                    0.5
                    if is_main_body_block
                    else max(6.5, base_font_size * (0.70 if len(content_text) > 140 else 0.76))
                )
                if layout_role == "marginalia":
                    min_readable_size = max(5.2, base_font_size * 0.58)
                success = self._insert_fitted_textbox(
                    target_page,
                    text_rect,
                    content_text,
                    text_font_name,
                    base_font_size,
                    style["color"],
                    align=text_align,
                    min_font_size=min_readable_size,
                    line_height=line_height,
                    measure_font=text_measure_font,
                    vertical_align=vertical_align,
                    force_manual_wrap=is_main_body_block or has_cjk(content_text),
                    first_line_indent=first_line_indent,
                )
                if not success:
                    fallback_count += 1
                    is_column_block = (
                        layout_role == "marginalia"
                        or block.get("layout_column") not in (None, -1)
                        or (
                            page_has_columns
                            and source_rect.width < original_rect.width * 0.68
                        )
                    )
                    fallback_right_edge = (
                        text_rect.x1
                        if is_column_block
                        else target_right_edge - 30
                    )
                    fallback_rect = fitz.Rect(
                        text_rect.x0,
                        text_rect.y0,
                        fallback_right_edge,
                        text_rect.y1 if is_main_body_block else min(original_rect.height - 12, max(text_rect.y1, bottom_limit)),
                    )
                    self._insert_fitted_textbox(
                        target_page,
                        fallback_rect,
                        content_text,
                        text_font_name,
                        base_font_size * 0.9,
                        style["color"],
                        align=text_align,
                        min_font_size=0.5 if is_main_body_block else max(5.8, base_font_size * 0.62),
                        line_height=line_height,
                        measure_font=text_measure_font,
                        vertical_align=vertical_align,
                        force_manual_wrap=is_main_body_block or has_cjk(content_text),
                        first_line_indent=first_line_indent,
                    )
                rendered_count += 1
                if inline_graphic_anchors:
                    self._copy_source_graphic_anchors(
                        target_page,
                        src_page,
                        inline_graphic_anchors,
                        x_offset,
                    )
            except Exception as e:
                failed_count += 1
                print(f"[DEBUG] Failed to insert text: {str(e)}")

        _pdf_perf_log(
            "translation_text_rendered",
            page=page_data.get("pageNum"),
            blocks=len(text_blocks),
            rendered=rendered_count,
            failed=failed_count,
            fallback=fallback_count,
            vertical=vertical_count,
            marginalia=marginalia_count,
            elapsed_ms=_elapsed_ms(started_at),
        )

    def _add_translated_page(self, doc, src_doc, page_data: Dict[str, Any]):
        page_started_at = time.perf_counter()
        page_num = page_data["pageNum"] - 1
        if page_num >= len(src_doc):
            return None

        src_page = src_doc[page_num]
        original_rect = src_page.rect
        new_page = doc.new_page(width=original_rect.width, height=original_rect.height)
        translated_blocks = self._get_translated_text_blocks(page_data)
        self._insert_source_page_visual_layer(
            new_page,
            src_page,
            fitz.Rect(0, 0, original_rect.width, original_rect.height),
            redact_blocks=translated_blocks,
        )
        required_scripts = detect_page_required_scripts(page_data)
        regular_font_path, bold_font_path = resolve_translation_font_paths(required_scripts)
        (
            regular_font_name,
            bold_font_name,
            regular_measure_font,
            bold_measure_font,
        ) = self._register_translation_fonts(
            new_page,
            regular_font_path,
            bold_font_path,
        )
        self._render_translated_text_blocks(
            new_page,
            src_page,
            page_data,
            original_rect,
            0,
            original_rect.width,
            regular_font_name,
            bold_font_name,
            regular_measure_font,
            bold_measure_font,
        )
        self._copy_source_block_regions(
            new_page,
            src_page,
            self._get_preserved_attribution_metadata_blocks(page_data),
            0,
        )
        _pdf_perf_log(
            "translated_page_rendered",
            page=page_data.get("pageNum"),
            blocks=len(translated_blocks),
            elapsed_ms=_elapsed_ms(page_started_at),
        )
        return new_page

    def _get_export_batch_size(self, output_type: str) -> int:
        env_name = (
            "PDF_TRANSLATED_EXPORT_BATCH_SIZE"
            if output_type == "translated"
            else "PDF_BILINGUAL_EXPORT_BATCH_SIZE"
        )
        default_size = (
            self.TRANSLATED_EXPORT_BATCH_SIZE
            if output_type == "translated"
            else self.BILINGUAL_EXPORT_BATCH_SIZE
        )
        try:
            return max(1, int(os.getenv(env_name, str(default_size))))
        except ValueError:
            return default_size

    def _create_temp_export_path(self, export_dir: str, prefix: str) -> str:
        temp_file = tempfile.NamedTemporaryFile(
            prefix=prefix,
            suffix=".pdf",
            dir=export_dir,
            delete=False,
        )
        temp_path = temp_file.name
        temp_file.close()
        return temp_path

    def _save_export_document(self, doc, output_path: str) -> None:
        if os.path.exists(output_path):
            os.remove(output_path)
        doc.save(output_path, deflate=True, garbage=4, clean=True)

    def _render_export_batch_to_path(
        self,
        src_doc,
        page_batch: List[Dict[str, Any]],
        batch_path: str,
        output_type: str,
    ) -> int:
        batch_started_at = time.perf_counter()
        doc = fitz.open()
        rendered_pages = 0
        try:
            for page_data in page_batch:
                self._clear_render_caches()
                if output_type == "translated":
                    rendered_page = self._add_translated_page(doc, src_doc, page_data)
                else:
                    rendered_page = self._add_bilingual_page(
                        doc,
                        src_doc,
                        page_data,
                        "",
                        "",
                    )

                if rendered_page is not None:
                    rendered_pages += 1

            if rendered_pages <= 0:
                return 0

            try:
                doc.subset_fonts()
            except Exception as e:
                print(f"[DEBUG] Failed to subset export batch fonts: {str(e)}")

            write_started_at = time.perf_counter()
            self._save_export_document(doc, batch_path)
            _pdf_perf_log(
                "export_batch_written",
                output_type=output_type,
                pages=rendered_pages,
                bytes=os.path.getsize(batch_path) if os.path.exists(batch_path) else None,
                write_ms=_elapsed_ms(write_started_at),
                elapsed_ms=_elapsed_ms(batch_started_at),
            )
        finally:
            doc.close()
            self._clear_render_caches()

        return rendered_pages

    def _merge_export_batches(self, batch_paths: List[str], output_path: str) -> None:
        if not batch_paths:
            raise FileNotFoundError("No export batches were rendered")

        if len(batch_paths) == 1:
            if os.path.exists(output_path):
                os.remove(output_path)
            os.replace(batch_paths[0], output_path)
            batch_paths.clear()
            return

        merge_started_at = time.perf_counter()
        final_doc = fitz.open()
        try:
            for batch_path in batch_paths:
                batch_doc = fitz.open(batch_path)
                try:
                    final_doc.insert_pdf(batch_doc)
                finally:
                    batch_doc.close()

            write_started_at = time.perf_counter()
            self._save_export_document(final_doc, output_path)
            _pdf_perf_log(
                "export_batches_merged",
                batches=len(batch_paths),
                pages=len(final_doc),
                bytes=os.path.getsize(output_path) if os.path.exists(output_path) else None,
                write_ms=_elapsed_ms(write_started_at),
                elapsed_ms=_elapsed_ms(merge_started_at),
            )
        finally:
            final_doc.close()

    def _write_export_pdf_to_path(
        self,
        file_id: str,
        page_results: Iterable[Dict[str, Any]],
        output_path: str,
        output_type: str,
    ) -> int:
        input_path = self.get_file_path(file_id)
        if not os.path.exists(input_path):
            raise FileNotFoundError("File not found")

        src_doc = fitz.open(input_path)
        export_dir = os.path.dirname(output_path) or self.output_dir
        batch_size = self._get_export_batch_size(output_type)
        batch_paths: List[str] = []
        page_batch: List[Dict[str, Any]] = []
        rendered_pages = 0
        try:
            for page_data in page_results:
                page_batch.append(page_data)
                if len(page_batch) < batch_size:
                    continue

                batch_path = self._create_temp_export_path(export_dir, f"{output_type}_batch_")
                try:
                    batch_rendered_pages = self._render_export_batch_to_path(src_doc, page_batch, batch_path, output_type)
                except Exception:
                    if os.path.exists(batch_path):
                        os.remove(batch_path)
                    raise
                if batch_rendered_pages > 0:
                    batch_paths.append(batch_path)
                    rendered_pages += batch_rendered_pages
                elif os.path.exists(batch_path):
                    os.remove(batch_path)
                page_batch = []

            if page_batch:
                batch_path = self._create_temp_export_path(export_dir, f"{output_type}_batch_")
                try:
                    batch_rendered_pages = self._render_export_batch_to_path(src_doc, page_batch, batch_path, output_type)
                except Exception:
                    if os.path.exists(batch_path):
                        os.remove(batch_path)
                    raise
                if batch_rendered_pages > 0:
                    batch_paths.append(batch_path)
                    rendered_pages += batch_rendered_pages
                elif os.path.exists(batch_path):
                    os.remove(batch_path)

            self._merge_export_batches(batch_paths, output_path)
        finally:
            src_doc.close()
            for batch_path in batch_paths:
                if os.path.exists(batch_path):
                    try:
                        os.remove(batch_path)
                    except OSError:
                        pass

        return rendered_pages

    def generate_translated_pdf_to_path(
        self,
        file_id: str,
        page_results: Iterable[Dict[str, Any]],
        output_path: str,
    ) -> int:
        started_at = time.perf_counter()
        rendered_pages = self._write_export_pdf_to_path(file_id, page_results, output_path, "translated")
        _pdf_perf_log(
            "translated_pdf_generated",
            pages=rendered_pages,
            bytes=os.path.getsize(output_path) if os.path.exists(output_path) else None,
            elapsed_ms=_elapsed_ms(started_at),
        )
        return rendered_pages

    def generate_bilingual_pdf_to_path(
        self,
        file_id: str,
        page_results: Iterable[Dict[str, Any]],
        output_path: str,
    ) -> int:
        started_at = time.perf_counter()
        rendered_pages = self._write_export_pdf_to_path(file_id, page_results, output_path, "bilingual")
        _pdf_perf_log(
            "bilingual_pdf_generated",
            pages=rendered_pages,
            bytes=os.path.getsize(output_path) if os.path.exists(output_path) else None,
            elapsed_ms=_elapsed_ms(started_at),
        )
        return rendered_pages

    def render_cached_export_pdf(self, task_id: str, file_id: str, output_type: str) -> int:
        result = self.load_translation_result(task_id)
        page_count = int(
            result.get("translatedPages")
            or result.get("requestedPages")
            or result.get("totalPages")
            or 0
        )
        if page_count <= 0:
            raise FileNotFoundError("Page results not found")

        export_dir = os.path.join(self.output_dir, task_id, "exports")
        os.makedirs(export_dir, exist_ok=True)

        temp_file = tempfile.NamedTemporaryFile(
            prefix=f"{task_id}_{output_type}_",
            suffix=".pdf",
            dir=export_dir,
            delete=False,
        )
        temp_path = temp_file.name
        temp_file.close()

        try:
            page_results = self.iter_page_translation_results(task_id, page_count)
            if output_type == "translated":
                rendered_pages = self.generate_translated_pdf_to_path(file_id, page_results, temp_path)
            else:
                rendered_pages = self.generate_bilingual_pdf_to_path(file_id, page_results, temp_path)

            if rendered_pages <= 0:
                raise FileNotFoundError("No translated pages were rendered")

            self.save_cached_export_pdf_file(task_id, output_type, temp_path)
            return rendered_pages
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    def generate_translated_pdf(self, file_id: str, translation_result: Dict[str, Any]) -> bytes:
        started_at = time.perf_counter()
        input_path = self.get_file_path(file_id)
        if not os.path.exists(input_path):
            raise FileNotFoundError("File not found")

        src_doc = fitz.open(input_path)
        doc = fitz.open()
        try:
            self._clear_render_caches()
            rendered_pages = 0
            for page_data in translation_result["pages"]:
                if self._add_translated_page(doc, src_doc, page_data) is not None:
                    rendered_pages += 1

            write_started_at = time.perf_counter()
            pdf_bytes = write_optimized_pdf(doc)
            _pdf_perf_log(
                "pdf_written",
                output_type="translated",
                pages=rendered_pages,
                bytes=len(pdf_bytes),
                elapsed_ms=_elapsed_ms(write_started_at),
            )
            _pdf_perf_log(
                "translated_pdf_generated",
                pages=rendered_pages,
                bytes=len(pdf_bytes),
                elapsed_ms=_elapsed_ms(started_at),
            )
            return pdf_bytes
        finally:
            self._clear_render_caches()
            doc.close()
            src_doc.close()

    def generate_bilingual_pdf(self, file_id: str, translation_result: Dict[str, Any]) -> bytes:
        started_at = time.perf_counter()
        input_path = self.get_file_path(file_id)
        if not os.path.exists(input_path):
            raise FileNotFoundError("File not found")

        src_doc = fitz.open(input_path)
        doc = fitz.open()
        try:
            self._clear_render_caches()
            rendered_pages = 0
            for page_data in translation_result.get("pages", []):
                page = self._add_bilingual_page(
                    doc,
                    src_doc,
                    page_data,
                    "",
                    "",
                )
                if page is not None:
                    rendered_pages += 1

            write_started_at = time.perf_counter()
            pdf_bytes = write_optimized_pdf(doc)
            _pdf_perf_log(
                "pdf_written",
                output_type="bilingual",
                pages=rendered_pages,
                bytes=len(pdf_bytes),
                elapsed_ms=_elapsed_ms(write_started_at),
            )
            _pdf_perf_log(
                "bilingual_pdf_generated",
                pages=rendered_pages,
                bytes=len(pdf_bytes),
                elapsed_ms=_elapsed_ms(started_at),
            )
            return pdf_bytes
        finally:
            self._clear_render_caches()
            doc.close()
            src_doc.close()
