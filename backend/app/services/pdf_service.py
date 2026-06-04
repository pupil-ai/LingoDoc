import fitz
import os
import uuid
import unicodedata
from typing import List, Dict, Any

from app.services.storage_service import storage_service


class PDFService:
    def __init__(self):
        self.upload_dir = os.path.join(os.path.dirname(__file__), "..", "..", "uploads")
        self.output_dir = os.path.join(os.path.dirname(__file__), "..", "..", "outputs")
        os.makedirs(self.upload_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)

    def get_file_storage_key(self, file_id: str) -> str:
        return f"uploads/{file_id}.pdf"

    def get_output_storage_key(self, task_id: str) -> str:
        return f"outputs/{task_id}.json"
    
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
    
    def extract_text_blocks(self, file_id: str, page_num: int) -> List[Dict[str, Any]]:
        file_path = self.get_file_path(file_id)
        if not os.path.exists(file_path):
            raise FileNotFoundError("File not found")
        
        doc = fitz.open(file_path)
        if page_num < 0 or page_num >= len(doc):
            raise ValueError("Invalid page number")
        
        page = doc[page_num]
        text_blocks = []
        
        # 使用 get_text("dict") 获取完整的文本信息，包括字体详情
        text_info = page.get_text("dict")
        
        for block in text_info.get("blocks", []):
            block_text = ""
            block_font_size = 0
            block_x0, block_y0, block_x1, block_y1 = float('inf'), float('inf'), 0, 0
            block_lines = []
            
            for line in block.get("lines", []):
                line_text_parts = []
                line_spans = []
                line_font_size = 0
                line_x0, line_y0, line_x1, line_y1 = float('inf'), float('inf'), 0, 0

                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    if not text:
                        continue
                    
                    # 跳过装饰性字符
                    is_decorative = (
                        len(text) == 1 and text in ["/", "-", "•", "·", "—", "–", "|", " "] or
                        (len(text) <= 2 and (span["bbox"][3] - span["bbox"][1]) < 18)
                    )
                    
                    if is_decorative:
                        continue
                    
                    line_text_parts.append(text)
                    line_font_size = max(line_font_size, span.get("size", 0))
                    line_x0 = min(line_x0, span["bbox"][0])
                    line_y0 = min(line_y0, span["bbox"][1])
                    line_x1 = max(line_x1, span["bbox"][2])
                    line_y1 = max(line_y1, span["bbox"][3])
                    line_spans.append({
                        "text": text,
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
                    block_font_size = max(block_font_size, span.get("size", 0))
                    block_x0 = min(block_x0, span["bbox"][0])
                    block_y0 = min(block_y0, span["bbox"][1])
                    block_x1 = max(block_x1, span["bbox"][2])
                    block_y1 = max(block_y1, span["bbox"][3])

                if line_text_parts:
                    line_text = " ".join(line_text_parts)
                    block_text += line_text + " "
                    block_lines.append({
                        "text": line_text,
                        "bbox": {"x0": line_x0, "y0": line_y0, "x1": line_x1, "y1": line_y1},
                        "font_size": line_font_size,
                        "spans": line_spans,
                    })
            
            if block_text.strip():
                clean_block_text = block_text.strip()
                text_blocks.append({
                    "type": "text",
                    "bbox": {"x0": block_x0, "y0": block_y0, "x1": block_x1, "y1": block_y1},
                    "text": clean_block_text,
                    "font_size": block_font_size,
                    "lines": block_lines,
                    "is_formula": self._is_formula_like_text(clean_block_text),
                })
        
        text_blocks.sort(key=lambda b: (b["bbox"]["y0"], b["bbox"]["x0"]))
        text_blocks = self._merge_text_blocks(text_blocks)
        
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
    
    def save_translation_result(self, task_id: str, result: Dict[str, Any]):
        import json
        content = json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")
        storage_service.save_bytes(self.get_output_storage_key(task_id), content)
    
    def load_translation_result(self, task_id: str) -> Dict[str, Any]:
        storage_key = self.get_output_storage_key(task_id)
        if not storage_service.exists(storage_key):
            raise FileNotFoundError("Result not found")
        
        import json
        return json.loads(storage_service.read_bytes(storage_key).decode("utf-8"))

    def _find_existing_font(self, font_paths: List[str]) -> str:
        for font_path in font_paths:
            if os.path.exists(font_path):
                return font_path
        return ""

    def _normalize_pdf_text(self, text: str) -> str:
        replacements = {
            "聽": " ",
            "馃挕": "\U0001F4A1",
            "馃洜": "\U0001F6E0",
            "馃殌": "\U0001F680",
            "馃尡": "\U0001F331",
        }
        normalized = text or ""
        for source, target in replacements.items():
            normalized = normalized.replace(source, target)
        return normalized.strip()

    def _has_cjk(self, text: str) -> bool:
        return any('\u4e00' <= char <= '\u9fff' for char in text)

    def _has_emoji(self, text: str) -> bool:
        return any(ord(char) > 0xFFFF for char in text)

    def _is_formula_like_text(self, text: str) -> bool:
        clean_text = self._normalize_pdf_text(text)
        compact_text = "".join(char for char in clean_text if not char.isspace())
        if len(compact_text) < 2:
            return False

        math_symbols = set("=<>±×÷√∑∫∞≈≠≤≥∂∆∇∈∉∪∩⊂⊆⊃⊇∧∨¬→←↔⇒⇔∴∵∝∠⊥∥∫∮∏∑^_{}[]|")
        greek_ranges = (
            ("\u0370", "\u03ff"),
            ("\u1f00", "\u1fff"),
        )

        def is_greek(char: str) -> bool:
            return any(start <= char <= end for start, end in greek_ranges)

        math_count = sum(1 for char in compact_text if char in math_symbols or is_greek(char))
        digit_count = sum(1 for char in compact_text if char.isdigit())
        letter_count = sum(1 for char in compact_text if char.isalpha() or "\u4e00" <= char <= "\u9fff")
        operator_count = sum(1 for char in compact_text if char in "+-*/=<>^_")
        symbol_ratio = (math_count + digit_count + operator_count) / max(len(compact_text), 1)

        if any(char in compact_text for char in "∑∫√≈≠≤≥±×÷∞∂∆∇") and letter_count <= len(compact_text) * 0.65:
            return True
        if "=" in compact_text and operator_count >= 1 and symbol_ratio >= 0.28:
            return True
        if math_count >= 2 and symbol_ratio >= 0.25:
            return True
        if len(compact_text) <= 28 and symbol_ratio >= 0.45 and letter_count <= digit_count + math_count + operator_count:
            return True

        return False

    def is_translatable_text_block(self, block: Dict[str, Any]) -> bool:
        if block.get("type") != "text":
            return False
        return not self._is_formula_like_text(block.get("text", ""))

    def _is_marker_prefix_char(self, char: str) -> bool:
        if not char:
            return False
        if char in {"\x00", "\ufffd", "\ufe0f", "\u200d"}:
            return True
        if ord(char) > 0xFFFF:
            return True
        return unicodedata.category(char) == "So" and char not in {"•", "·", "○", "●", "□"}

    def _split_marker_prefix(self, text: str):
        clean_text = self._normalize_pdf_text(text)
        marker_chars = []
        saw_marker = False
        index = 0

        while index < len(clean_text):
            char = clean_text[index]
            if char.isspace() and saw_marker:
                index += 1
                continue
            if self._is_marker_prefix_char(char):
                saw_marker = True
                if char not in {"\x00", "\ufffd", "\ufe0f", "\u200d"}:
                    marker_chars.append(char)
                index += 1
                continue
            break

        if not saw_marker:
            return "", clean_text, False

        marker = "".join(marker_chars) or "•"
        return marker, clean_text[index:].strip(), True

    def _block_rect(self, block: Dict[str, Any]) -> fitz.Rect:
        bbox = block.get("bbox", {})
        return fitz.Rect(bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"])

    def _is_marker_heading(self, block: Dict[str, Any]) -> bool:
        text = self._normalize_pdf_text(block.get("text", ""))
        if not text:
            return False

        marker, heading_text, saw_marker = self._split_marker_prefix(text)
        if not saw_marker:
            return False

        line_count = len([
            line for line in block.get("lines", [])
            if self._normalize_pdf_text(line.get("text", ""))
        ])
        if line_count > 2:
            return False

        rect = self._block_rect(block)
        font_size = self._font_size_for_merge(block, rect)
        if len(heading_text) > 60:
            return False
        if any(char in heading_text for char in ".。!?！？:：;；") and len(heading_text) > 20:
            return False

        return bool(marker) and font_size >= 10

    def _font_size_for_merge(self, block: Dict[str, Any], rect: fitz.Rect) -> float:
        font_size = float(block.get("font_size") or 0)
        if font_size > 0:
            return font_size

        line_sizes = [
            float(line.get("font_size") or 0)
            for line in block.get("lines", [])
            if float(line.get("font_size") or 0) > 0
        ]
        if line_sizes:
            sorted_sizes = sorted(line_sizes)
            return sorted_sizes[len(sorted_sizes) // 2]

        return min(rect.height, 24)

    def _can_merge_text_blocks(self, previous: Dict[str, Any], current: Dict[str, Any]) -> bool:
        if previous.get("type") != "text" or current.get("type") != "text":
            return False
        if previous.get("is_formula") or current.get("is_formula"):
            return False
        if self._is_marker_heading(previous) or self._is_marker_heading(current):
            return False

        previous_rect = self._block_rect(previous)
        current_rect = self._block_rect(current)
        if current_rect.y0 <= previous_rect.y0 or current_rect.y0 < previous_rect.y1 - 1:
            return False

        previous_font_size = self._font_size_for_merge(previous, previous_rect)
        current_font_size = self._font_size_for_merge(current, current_rect)
        if previous_font_size <= 0 or current_font_size <= 0:
            return False

        font_delta = abs(previous_font_size - current_font_size) / max(previous_font_size, current_font_size)
        if font_delta > 0.25:
            return False

        vertical_gap = current_rect.y0 - previous_rect.y1
        max_gap = max(previous_font_size, current_font_size, 10) * 0.9
        if vertical_gap < -1 or vertical_gap > max_gap:
            return False

        left_delta = abs(previous_rect.x0 - current_rect.x0)
        if left_delta > max(previous_font_size * 1.2, 24):
            return False

        return True

    def _merge_two_text_blocks(self, previous: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
        previous_rect = self._block_rect(previous)
        current_rect = self._block_rect(current)
        merged_rect = previous_rect | current_rect
        merged = dict(previous)
        merged["bbox"] = {
            "x0": merged_rect.x0,
            "y0": merged_rect.y0,
            "x1": merged_rect.x1,
            "y1": merged_rect.y1,
        }
        merged["text"] = " ".join(
            part for part in [previous.get("text", "").strip(), current.get("text", "").strip()]
            if part
        )

        translated_parts = [
            previous.get("translatedText", "").strip(),
            current.get("translatedText", "").strip(),
        ]
        if any(translated_parts):
            merged["translatedText"] = " ".join(part for part in translated_parts if part)

        merged["font_size"] = max(
            self._font_size_for_merge(previous, previous_rect),
            self._font_size_for_merge(current, current_rect),
        )
        merged["lines"] = previous.get("lines", []) + current.get("lines", [])
        merged["merged_blocks"] = previous.get("merged_blocks", 1) + current.get("merged_blocks", 1)
        return merged

    def _merge_text_blocks(self, text_blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        merged_blocks = []
        for block in sorted(text_blocks, key=lambda item: (item["bbox"]["y0"], item["bbox"]["x0"])):
            if merged_blocks and self._can_merge_text_blocks(merged_blocks[-1], block):
                merged_blocks[-1] = self._merge_two_text_blocks(merged_blocks[-1], block)
            else:
                merged_blocks.append(dict(block))
        return merged_blocks

    def _color_from_int(self, color: int):
        return (
            ((color >> 16) & 255) / 255,
            ((color >> 8) & 255) / 255,
            (color & 255) / 255,
        )

    def _color_distance(self, first, second) -> float:
        return sum((first[index] - second[index]) ** 2 for index in range(3)) ** 0.5

    def _relative_luminance(self, color) -> float:
        def channel_luminance(value: float) -> float:
            return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

        red, green, blue = color
        return (
            0.2126 * channel_luminance(red) +
            0.7152 * channel_luminance(green) +
            0.0722 * channel_luminance(blue)
        )

    def _contrast_ratio(self, first, second) -> float:
        first_luminance = self._relative_luminance(first)
        second_luminance = self._relative_luminance(second)
        lighter = max(first_luminance, second_luminance)
        darker = min(first_luminance, second_luminance)
        return (lighter + 0.05) / (darker + 0.05)

    def _ensure_readable_color(self, color, background_color):
        if not color or len(color) != 3:
            return fitz.utils.getColor("black")

        if not background_color or len(background_color) != 3:
            return color

        if self._contrast_ratio(color, background_color) < 1.6:
            black = fitz.utils.getColor("black")
            white = fitz.utils.getColor("white")
            return (
                black
                if self._contrast_ratio(black, background_color) >= self._contrast_ratio(white, background_color)
                else white
            )
        return color

    def _estimate_background_color(self, page, rect: fitz.Rect, source_block: Dict[str, Any] = None):
        text_colors = []
        if source_block:
            for line in source_block.get("lines", []):
                for span in line.get("spans", []):
                    if span.get("text", "").strip():
                        text_colors.append(self._color_from_int(span.get("color", 0)))

        clip_rect = fitz.Rect(
            max(page.rect.x0, rect.x0 - 4),
            max(page.rect.y0, rect.y0 - 4),
            min(page.rect.x1, rect.x1 + 4),
            min(page.rect.y1, rect.y1 + 4),
        )
        if clip_rect.is_empty:
            return fitz.utils.getColor("white")

        try:
            pixmap = page.get_pixmap(matrix=fitz.Matrix(0.5, 0.5), clip=clip_rect, alpha=False)
        except Exception:
            return fitz.utils.getColor("white")

        counts = {}
        fallback_counts = {}
        channels = pixmap.n
        if pixmap.width <= 0 or pixmap.height <= 0 or channels < 3:
            return fitz.utils.getColor("white")

        step = max(1, int(((pixmap.width * pixmap.height) / 5000) ** 0.5))
        samples = pixmap.samples
        def add_sample(aggregates, bucket, red, green, blue):
            if bucket not in aggregates:
                aggregates[bucket] = [0, 0, 0, 0]
            aggregates[bucket][0] += 1
            aggregates[bucket][1] += red
            aggregates[bucket][2] += green
            aggregates[bucket][3] += blue

        for y in range(0, pixmap.height, step):
            row_offset = y * pixmap.width * channels
            for x in range(0, pixmap.width, step):
                offset = row_offset + x * channels
                red, green, blue = samples[offset], samples[offset + 1], samples[offset + 2]
                rgb = (red / 255, green / 255, blue / 255)
                bucket = (red // 16 * 16, green // 16 * 16, blue // 16 * 16)
                add_sample(fallback_counts, bucket, red, green, blue)

                if any(self._color_distance(rgb, text_color) < 0.18 for text_color in text_colors):
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

    def _rect_overlap_ratio(self, first: fitz.Rect, second: fitz.Rect) -> float:
        overlap = first & second
        if overlap.is_empty or first.get_area() <= 0:
            return 0
        return overlap.get_area() / first.get_area()

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
                if not self._normalize_pdf_text(line.get("text", "")):
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

            clean_text = self._normalize_pdf_text(source_block.get("text", ""))
            line_count = len(line_rects)
            median_size = sorted(line_sizes)[len(line_sizes) // 2] if line_sizes else max(rect.height, 10)

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
                        if self._rect_overlap_ratio(span_rect, rect) < 0.2:
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
        color = self._color_from_int(base_color) if color_weights else fitz.utils.getColor("black")
        font_name = fonts[0] if fonts else ""
        background_color = self._estimate_background_color(page, rect, source_block)

        return {
            "font_size": max(font_size, 6),
            "color": self._ensure_readable_color(color, background_color),
            "background_color": background_color,
            "font_name": font_name,
            "is_bold": bool(total_weight and bold_weight / total_weight >= 0.45),
            "align": self._detect_block_alignment(page, rect, source_block),
        }

    def _split_leading_marker(self, translated_text: str, source_text: str):
        translated_marker, translated, translated_has_marker = self._split_marker_prefix(translated_text)
        source_marker, _, source_has_marker = self._split_marker_prefix(source_text)

        marker = ""
        if translated_has_marker:
            marker = translated_marker
        elif source_has_marker:
            marker = source_marker
            translated = self._normalize_pdf_text(translated_text)

        return marker, translated

    def _insert_source_page_visual_layer(self, target_page, source_page, target_rect: fitz.Rect):
        try:
            pixmap = source_page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            target_page.insert_image(target_rect, stream=pixmap.tobytes("png"))
            return
        except Exception as e:
            print(f"[DEBUG] Failed to insert source visual layer: {str(e)}")

        target_page.draw_rect(
            target_rect,
            color=fitz.utils.getColor("white"),
            fill=fitz.utils.getColor("white"),
        )

    def _should_preserve_marker_span(self, span_text: str) -> bool:
        clean_text = self._normalize_pdf_text(span_text)
        if not clean_text:
            return True

        marker, heading_text, saw_marker = self._split_marker_prefix(clean_text)
        if saw_marker and marker and not heading_text:
            return True

        return clean_text in {"•", "·", "○", "●", "□", "-", "/", "\\", "|"}

    def _cover_source_text_on_translation_side(
        self,
        target_page,
        block: Dict[str, Any],
        page_width: float,
        fallback_rect: fitz.Rect,
        fill_color,
        preserve_marker: bool = False,
    ):
        span_rects = []
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if preserve_marker and self._should_preserve_marker_span(span.get("text", "")):
                    continue

                bbox = span.get("bbox")
                if not bbox:
                    continue

                try:
                    span_rect = fitz.Rect(bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"])
                except Exception:
                    continue

                if not span_rect.is_empty:
                    span_rects.append(span_rect)

        if not span_rects:
            span_rects = [fallback_rect]

        for span_rect in span_rects:
            underline_padding = max(1.8, span_rect.height * 0.12)
            cover_rect = fitz.Rect(
                page_width + span_rect.x0 - 0.6,
                span_rect.y0 - 0.6,
                page_width + span_rect.x1 + 0.6,
                span_rect.y1 + underline_padding,
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
                text = self._normalize_pdf_text(span.get("text", ""))
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

    def _copy_source_marker(
        self,
        target_page,
        source_doc,
        page_num: int,
        source_rect: fitz.Rect,
        target_rect: fitz.Rect,
        font_size: float,
    ) -> float:
        if source_rect.is_empty or target_rect.is_empty:
            return 0

        clip_width = min(source_rect.width, max(font_size * 1.25, source_rect.height * 0.7))
        clip_rect = fitz.Rect(
            source_rect.x0,
            source_rect.y0,
            min(source_rect.x1, source_rect.x0 + clip_width),
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

    def _measure_text_width(self, text: str, font_size: float, measure_font=None, font_name: str = "helv") -> float:
        if not text:
            return 0
        if measure_font:
            return measure_font.text_length(text, fontsize=font_size)
        return fitz.get_text_length(text, fontname=font_name, fontsize=font_size)

    def _wrap_text_for_rect(
        self,
        text: str,
        max_width: float,
        font_size: float,
        measure_font=None,
        font_name: str = "helv",
    ) -> List[str]:
        wrapped_lines = []
        for paragraph in self._normalize_pdf_text(text).splitlines():
            tokens = []
            current_word = ""

            for char in paragraph:
                is_cjk = '\u4e00' <= char <= '\u9fff'
                is_cjk_punctuation = char in "，。！？；：（）《》“”‘’、"
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

                candidate = f"{line}{token}" if line else token.strip()
                if self._measure_text_width(candidate, font_size, measure_font, font_name) <= max_width:
                    line = candidate
                    continue

                if line:
                    wrapped_lines.append(line.rstrip())
                    line = token.strip()

                while (
                    line
                    and self._measure_text_width(line, font_size, measure_font, font_name) > max_width
                    and len(line) > 1
                ):
                    split_index = len(line)
                    while split_index > 1:
                        head = line[:split_index]
                        if self._measure_text_width(head, font_size, measure_font, font_name) <= max_width:
                            break
                        split_index -= 1
                    wrapped_lines.append(line[:split_index].rstrip())
                    line = line[split_index:].lstrip()

            if line:
                wrapped_lines.append(line.rstrip())

        return wrapped_lines

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
    ) -> bool:
        clean_text = self._normalize_pdf_text(text)
        if not clean_text or rect.width <= 0 or rect.height <= 0:
            return False

        current_size = max(font_size, min_font_size)
        while current_size >= min_font_size:
            lines = self._wrap_text_for_rect(
                clean_text,
                rect.width,
                current_size,
                measure_font=measure_font,
                font_name=font_name,
            )
            line_step = current_size * line_height
            required_height = current_size + max(len(lines) - 1, 0) * line_step

            if lines and required_height <= rect.height:
                top_offset = 0
                if vertical_align == "middle":
                    top_offset = max((rect.height - required_height) / 2, 0)
                baseline = rect.y0 + top_offset + current_size

                if align == fitz.TEXT_ALIGN_LEFT:
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
                    page.insert_text(
                        (text_x, baseline),
                        line,
                        fontsize=current_size,
                        fontname=font_name,
                        color=color,
                    )
                    baseline += line_step
                return True

            current_size *= 0.9

        return False

    def _get_translation_font_paths(self):
        regular_chinese_font_path = self._find_existing_font([
            "C:\\Windows\\Fonts\\msyh.ttc",
            "C:\\Windows\\Fonts\\simsun.ttc",
            "C:\\Windows\\Fonts\\simhei.ttf",
            "C:\\Windows\\Fonts\\simkai.ttf",
        ])
        bold_chinese_font_path = self._find_existing_font([
            "C:\\Windows\\Fonts\\msyhbd.ttc",
            "C:\\Windows\\Fonts\\simhei.ttf",
            "C:\\Windows\\Fonts\\simsunb.ttf",
            regular_chinese_font_path,
        ])
        return regular_chinese_font_path, bold_chinese_font_path

    def _register_translation_fonts(self, page, regular_chinese_font_path: str, bold_chinese_font_path: str):
        regular_font_registered = False
        if regular_chinese_font_path:
            try:
                page.insert_font(fontfile=regular_chinese_font_path, fontname="custom_chinese_regular")
                regular_font_registered = True
            except Exception as e:
                print(f"[DEBUG] Failed to register font: {str(e)}")

        bold_font_registered = False
        if bold_chinese_font_path:
            try:
                page.insert_font(fontfile=bold_chinese_font_path, fontname="custom_chinese_bold")
                bold_font_registered = True
            except Exception as e:
                print(f"[DEBUG] Failed to register bold font: {str(e)}")

        regular_font_name = "custom_chinese_regular" if regular_font_registered else "helv"
        bold_font_name = "custom_chinese_bold" if bold_font_registered else regular_font_name
        try:
            regular_measure_font = (
                fitz.Font(fontfile=regular_chinese_font_path)
                if regular_font_registered
                else fitz.Font("helv")
            )
        except Exception:
            regular_measure_font = fitz.Font("helv")
        try:
            bold_measure_font = (
                fitz.Font(fontfile=bold_chinese_font_path)
                if bold_font_registered
                else regular_measure_font
            )
        except Exception:
            bold_measure_font = regular_measure_font

        return regular_font_name, bold_font_name, regular_measure_font, bold_measure_font

    def _get_translated_text_blocks(self, page_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        text_blocks = [
            block for block in page_data.get("textBlocks", [])
            if block.get("type") == "text"
            and block.get("translatedText")
            and not block.get("is_formula")
            and self.is_translatable_text_block(block)
        ]
        return self._merge_text_blocks(text_blocks)

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
        text_blocks = self._get_translated_text_blocks(page_data)

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
                if self._normalize_pdf_text(line.get("text", ""))
            ])
            translated_text = self._normalize_pdf_text(block.get("translatedText", ""))
            source_text = self._normalize_pdf_text(block.get("text", ""))
            marker, content_text = self._split_leading_marker(translated_text, source_text)
            if not content_text:
                content_text = translated_text

            style = self._get_block_style(src_page, source_rect, block.get("font_size") or 10, block)
            text_font_name = bold_font_name if style["is_bold"] else regular_font_name
            text_measure_font = bold_measure_font if style["is_bold"] else regular_measure_font
            base_font_size = float(block.get("font_size") or style["font_size"])
            if self._has_cjk(content_text):
                base_font_size *= 0.86
            if marker:
                base_font_size = max(base_font_size, style["font_size"] * 0.9)
            base_font_size = max(min(base_font_size, source_rect.height * 0.95), 5.5)

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
            target_bottom = min(
                original_rect.height - 12,
                max(bottom_limit, source_rect.y1 + 2, source_rect.y0 + min_height),
            )
            translation_start_x = (
                source_rect.x0
                if marker
                else self._translation_start_x(block, source_rect, base_font_size)
            )

            target_rect = fitz.Rect(
                x_offset + translation_start_x,
                max(0, source_rect.y0 - 1),
                min(target_right_edge - 24, x_offset + source_rect.x1 + 2),
                min(original_rect.height - 12, target_bottom),
            )
            if target_rect.width < base_font_size * 2:
                target_rect.x1 = min(target_right_edge - 24, target_rect.x0 + base_font_size * 4)

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
                marker_width = base_font_size * 1.35
                text_rect = fitz.Rect(
                    min(target_rect.x1, target_rect.x0 + marker_width),
                    target_rect.y0,
                    target_rect.x1,
                    target_rect.y1,
                )

            try:
                line_height = 1.42 if self._has_cjk(content_text) and len(content_text) > 80 else 1.36 if self._has_cjk(content_text) else 1.2
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
                min_readable_size = max(6.5, base_font_size * (0.70 if len(content_text) > 140 else 0.76))
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
                )
                if not success:
                    fallback_rect = fitz.Rect(
                        text_rect.x0,
                        text_rect.y0,
                        target_right_edge - 30,
                        min(original_rect.height - 12, max(text_rect.y1, bottom_limit)),
                    )
                    self._insert_fitted_textbox(
                        target_page,
                        fallback_rect,
                        content_text,
                        text_font_name,
                        base_font_size * 0.9,
                        style["color"],
                        align=text_align,
                        min_font_size=max(5.8, base_font_size * 0.62),
                        line_height=line_height,
                        measure_font=text_measure_font,
                        vertical_align=vertical_align,
                    )
            except Exception as e:
                print(f"[DEBUG] Failed to insert text: {str(e)}")

    def generate_translated_pdf(self, file_id: str, translation_result: Dict[str, Any]) -> bytes:
        input_path = self.get_file_path(file_id)
        if not os.path.exists(input_path):
            raise FileNotFoundError("File not found")

        src_doc = fitz.open(input_path)
        doc = fitz.open()
        regular_chinese_font_path, bold_chinese_font_path = self._get_translation_font_paths()

        for page_data in translation_result["pages"]:
            page_num = page_data["pageNum"] - 1
            if page_num >= len(src_doc):
                continue

            src_page = src_doc[page_num]
            original_rect = src_page.rect
            new_page = doc.new_page(width=original_rect.width, height=original_rect.height)
            self._insert_source_page_visual_layer(
                new_page,
                src_page,
                fitz.Rect(0, 0, original_rect.width, original_rect.height),
            )
            (
                regular_font_name,
                bold_font_name,
                regular_measure_font,
                bold_measure_font,
            ) = self._register_translation_fonts(new_page, regular_chinese_font_path, bold_chinese_font_path)
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

        pdf_bytes = doc.write(deflate=True, garbage=4)
        doc.close()
        src_doc.close()

        return pdf_bytes
        
        doc = fitz.open(input_path)
        
        # 查找可用的中文字体
        font_paths = [
            "C:\\Windows\\Fonts\\simhei.ttf",
            "C:\\Windows\\Fonts\\msyh.ttc",
            "C:\\Windows\\Fonts\\simkai.ttf",
        ]
        chinese_font_path = None
        for font_path in font_paths:
            if os.path.exists(font_path):
                chinese_font_path = font_path
                break
        
        for page_data in translation_result["pages"]:
            page_num = page_data["pageNum"] - 1
            if page_num >= len(doc):
                continue
            
            page = doc[page_num]
            
            # 注册中文字体到页面
            font_registered = False
            if chinese_font_path:
                try:
                    page.insert_font(fontfile=chinese_font_path, fontname="custom_chinese")
                    font_registered = True
                except Exception as e:
                    print(f"[DEBUG] Failed to register font: {str(e)}")
            
            blocks_to_process = []
            for block in page_data.get("textBlocks", []):
                if block.get("type") == "text":
                    bbox = block["bbox"]
                    rect = fitz.Rect(bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"])
                    blocks_to_process.append({
                        "rect": rect,
                        "text": block["text"],
                        "translated": block["translatedText"],
                        "height": bbox["y1"] - bbox["y0"],
                    })
            
            # 先擦除原文本
            for item in blocks_to_process:
                page.add_redact_annot(item["rect"], fill=fitz.utils.getColor("white"))
            page.apply_redactions()
            
            # 插入新的翻译文本
            for item in blocks_to_process:
                if not item["translated"]:
                    continue
                
                block_height = item["height"]
                font_size = max(block_height * 0.6, 8)
                
                # 扩展文本框确保完整显示
                rect = item["rect"]
                expanded_rect = fitz.Rect(
                    rect.x0,
                    max(0, rect.y0 - block_height * 0.3),
                    rect.x1 + 20,  # 稍微扩宽
                    min(page.rect.height, rect.y1 + block_height * 0.5)
                )
                
                try:
                    has_chinese = any('\u4e00' <= c <= '\u9fff' for c in item["translated"])
                    
                    if has_chinese and font_registered:
                        result = page.insert_textbox(
                            expanded_rect,
                            item["translated"],
                            fontsize=font_size,
                            fontname="custom_chinese",
                            color=fitz.utils.getColor("black"),
                            align=fitz.TEXT_ALIGN_LEFT,
                        )
                        if result < 0:
                            smaller_font = font_size * 0.8
                            page.insert_textbox(
                                expanded_rect,
                                item["translated"],
                                fontsize=smaller_font,
                                fontname="custom_chinese",
                                color=fitz.utils.getColor("black"),
                                align=fitz.TEXT_ALIGN_LEFT,
                            )
                    else:
                        result = page.insert_textbox(
                            expanded_rect,
                            item["translated"],
                            fontsize=font_size,
                            color=fitz.utils.getColor("black"),
                            align=fitz.TEXT_ALIGN_LEFT,
                        )
                        if result < 0:
                            smaller_font = font_size * 0.8
                            page.insert_textbox(
                                expanded_rect,
                                item["translated"],
                                fontsize=smaller_font,
                                color=fitz.utils.getColor("black"),
                                align=fitz.TEXT_ALIGN_LEFT,
                            )
                except Exception as e:
                    print(f"[DEBUG] Failed to insert translated text: {str(e)}")
                    pass
        
        pdf_bytes = doc.write(deflate=True, garbage=4)
        doc.close()
        
        return pdf_bytes

    def generate_bilingual_pdf(self, file_id: str, translation_result: Dict[str, Any]) -> bytes:
        input_path = self.get_file_path(file_id)
        if not os.path.exists(input_path):
            raise FileNotFoundError("File not found")

        src_doc = fitz.open(input_path)
        doc = fitz.open()

        regular_chinese_font_path = self._find_existing_font([
            "C:\\Windows\\Fonts\\msyh.ttc",
            "C:\\Windows\\Fonts\\simsun.ttc",
            "C:\\Windows\\Fonts\\simhei.ttf",
            "C:\\Windows\\Fonts\\simkai.ttf",
        ])
        bold_chinese_font_path = self._find_existing_font([
            "C:\\Windows\\Fonts\\msyhbd.ttc",
            "C:\\Windows\\Fonts\\simhei.ttf",
            "C:\\Windows\\Fonts\\simsunb.ttf",
            regular_chinese_font_path,
        ])

        for page_data in translation_result["pages"]:
            page_num = page_data["pageNum"] - 1
            if page_num >= len(src_doc):
                continue

            src_page = src_doc[page_num]
            original_rect = src_page.rect
            page_width = original_rect.width

            new_page = doc.new_page(width=original_rect.width * 2, height=original_rect.height)
            new_page.show_pdf_page(fitz.Rect(0, 0, page_width, original_rect.height), src_doc, page_num)

            right_bg_rect = fitz.Rect(page_width, 0, page_width * 2, original_rect.height)
            self._insert_source_page_visual_layer(new_page, src_page, right_bg_rect)
            new_page.draw_line(
                (page_width, 0),
                (page_width, original_rect.height),
                color=fitz.utils.getColor("gray"),
                width=1.0,
            )

            regular_font_registered = False
            if regular_chinese_font_path:
                try:
                    new_page.insert_font(fontfile=regular_chinese_font_path, fontname="custom_chinese_regular")
                    regular_font_registered = True
                except Exception as e:
                    print(f"[DEBUG] Failed to register font: {str(e)}")

            bold_font_registered = False
            if bold_chinese_font_path:
                try:
                    new_page.insert_font(fontfile=bold_chinese_font_path, fontname="custom_chinese_bold")
                    bold_font_registered = True
                except Exception as e:
                    print(f"[DEBUG] Failed to register bold font: {str(e)}")

            regular_font_name = "custom_chinese_regular" if regular_font_registered else "helv"
            bold_font_name = "custom_chinese_bold" if bold_font_registered else regular_font_name
            try:
                regular_measure_font = (
                    fitz.Font(fontfile=regular_chinese_font_path)
                    if regular_font_registered
                    else fitz.Font("helv")
                )
            except Exception:
                regular_measure_font = fitz.Font("helv")
            try:
                bold_measure_font = (
                    fitz.Font(fontfile=bold_chinese_font_path)
                    if bold_font_registered
                    else regular_measure_font
                )
            except Exception:
                bold_measure_font = regular_measure_font

            text_blocks = [
                block for block in page_data.get("textBlocks", [])
                if block.get("type") == "text"
                and block.get("translatedText")
                and not block.get("is_formula")
                and self.is_translatable_text_block(block)
            ]
            text_blocks = self._merge_text_blocks(text_blocks)

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
                    if self._normalize_pdf_text(line.get("text", ""))
                ])
                translated_text = self._normalize_pdf_text(block.get("translatedText", ""))
                source_text = self._normalize_pdf_text(block.get("text", ""))
                marker, content_text = self._split_leading_marker(translated_text, source_text)
                if not content_text:
                    content_text = translated_text

                style = self._get_block_style(src_page, source_rect, block.get("font_size") or 10, block)
                text_font_name = bold_font_name if style["is_bold"] else regular_font_name
                text_measure_font = bold_measure_font if style["is_bold"] else regular_measure_font
                base_font_size = float(block.get("font_size") or style["font_size"])
                if self._has_cjk(content_text):
                    base_font_size *= 0.86
                if marker:
                    base_font_size = max(base_font_size, style["font_size"] * 0.9)
                base_font_size = max(min(base_font_size, source_rect.height * 0.95), 5.5)

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
                target_bottom = min(
                    original_rect.height - 12,
                    max(bottom_limit, source_rect.y1 + 2, source_rect.y0 + min_height),
                )
                translation_start_x = (
                    source_rect.x0
                    if marker
                    else self._translation_start_x(block, source_rect, base_font_size)
                )

                right_rect = fitz.Rect(
                    page_width + translation_start_x,
                    max(0, source_rect.y0 - 1),
                    min(page_width * 2 - 24, page_width + source_rect.x1 + 2),
                    min(original_rect.height - 12, target_bottom),
                )
                if right_rect.width < base_font_size * 2:
                    right_rect.x1 = min(page_width * 2 - 24, right_rect.x0 + base_font_size * 4)

                self._cover_source_text_on_translation_side(
                    new_page,
                    block,
                    page_width,
                    source_rect,
                    style["background_color"],
                    preserve_marker=bool(marker),
                )

                text_rect = right_rect
                if marker:
                    marker_width = base_font_size * 1.35
                    text_rect = fitz.Rect(
                        min(right_rect.x1, right_rect.x0 + marker_width),
                        right_rect.y0,
                        right_rect.x1,
                        right_rect.y1,
                    )

                try:
                    line_height = 1.42 if self._has_cjk(content_text) and len(content_text) > 80 else 1.36 if self._has_cjk(content_text) else 1.2
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
                    min_readable_size = max(6.5, base_font_size * (0.70 if len(content_text) > 140 else 0.76))
                    success = self._insert_fitted_textbox(
                        new_page,
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
                    )
                    if not success:
                        fallback_rect = fitz.Rect(
                            text_rect.x0,
                            text_rect.y0,
                            page_width * 2 - 30,
                            min(original_rect.height - 12, max(text_rect.y1, bottom_limit)),
                        )
                        self._insert_fitted_textbox(
                            new_page,
                            fallback_rect,
                            content_text,
                            text_font_name,
                            base_font_size * 0.9,
                            style["color"],
                            align=text_align,
                            min_font_size=max(5.8, base_font_size * 0.62),
                            line_height=line_height,
                            measure_font=text_measure_font,
                            vertical_align=vertical_align,
                        )
                except Exception as e:
                    print(f"[DEBUG] Failed to insert text: {str(e)}")

        pdf_bytes = doc.write(deflate=True, garbage=4)
        doc.close()
        src_doc.close()

        return pdf_bytes
    
    def _generate_bilingual_pdf_legacy(self, file_id: str, translation_result: Dict[str, Any]) -> bytes:
        input_path = self.get_file_path(file_id)
        if not os.path.exists(input_path):
            raise FileNotFoundError("File not found")
        
        src_doc = fitz.open(input_path)
        doc = fitz.open()
        
        # 查找可用的中文字体
        font_paths = [
            "C:\\Windows\\Fonts\\simhei.ttf",
            "C:\\Windows\\Fonts\\msyh.ttc",
            "C:\\Windows\\Fonts\\simkai.ttf",
        ]
        chinese_font_path = None
        for font_path in font_paths:
            if os.path.exists(font_path):
                chinese_font_path = font_path
                break
        
        for page_data in translation_result["pages"]:
            page_num = page_data["pageNum"] - 1
            if page_num >= len(src_doc):
                continue
            
            src_page = src_doc[page_num]
            original_rect = src_page.rect
            page_width = original_rect.width
            
            # 创建新的宽幅页面（左右各一半）
            new_page = doc.new_page(width=original_rect.width * 2, height=original_rect.height)
            
            # 左侧：渲染源文档页面
            left_rect = fitz.Rect(0, 0, page_width, original_rect.height)
            new_page.show_pdf_page(left_rect, src_doc, page_num)
            
            # 右侧：白色背景
            right_bg_rect = fitz.Rect(page_width, 0, page_width * 2, original_rect.height)
            new_page.draw_rect(right_bg_rect, color=fitz.utils.getColor("white"), fill=fitz.utils.getColor("white"))
            
            # 中间分隔线
            new_page.draw_line(
                (page_width, 0), (page_width, original_rect.height),
                color=fitz.utils.getColor("gray"), width=1.0
            )
            
            # 注册中文字体到页面
            font_registered = False
            if chinese_font_path:
                try:
                    new_page.insert_font(fontfile=chinese_font_path, fontname="custom_chinese")
                    font_registered = True
                except Exception as e:
                    print(f"[DEBUG] Failed to register font: {str(e)}")
            
            # 获取原文的完整文本信息（用于逐行匹配）
            text_info = src_page.get_text("dict")
            
            # 获取整页翻译结果（字段名是 translated）
            full_translation = page_data.get("translated", "")
            if not full_translation:
                # 如果没有整页翻译，使用块级翻译
                full_translation = "\n".join(
                    block["translatedText"] for block in page_data.get("textBlocks", [])
                    if block.get("type") == "text" and block.get("translatedText")
                )
            
            # 将翻译按段落分割
            translation_paragraphs = [p.strip() for p in full_translation.split('\n') if p.strip()]
            paragraph_idx = 0
            
            # 逐块写入译文，使用原文的精确字体信息
            for block in text_info.get("blocks", []):
                block_text = ""
                block_lines = []
                
                # 收集块中的所有行
                for line in block.get("lines", []):
                    line_text = ""
                    line_font_size = 0
                    line_x0, line_y0, line_x1, line_y1 = float('inf'), float('inf'), 0, 0
                    
                    for span in line.get("spans", []):
                        text = span.get("text", "").strip()
                        if not text:
                            continue
                        
                        # 跳过装饰性字符
                        is_decorative = (
                            len(text) == 1 and text in ["/", "-", "•", "·", "—", "–", "|", " "] or
                            (len(text) <= 2 and (span["bbox"][3] - span["bbox"][1]) < 18)
                        )
                        
                        if is_decorative:
                            continue
                        
                        line_text += text + " "
                        line_font_size = max(line_font_size, span.get("size", 10))
                        line_x0 = min(line_x0, span["bbox"][0])
                        line_y0 = min(line_y0, span["bbox"][1])
                        line_x1 = max(line_x1, span["bbox"][2])
                        line_y1 = max(line_y1, span["bbox"][3])
                    
                    if line_text.strip():
                        block_lines.append({
                            "text": line_text.strip(),
                            "font_size": line_font_size,
                            "x0": line_x0,
                            "y0": line_y0,
                            "x1": line_x1,
                            "y1": line_y1,
                        })
                    block_text += line_text
                
                if block_text.strip() and paragraph_idx < len(translation_paragraphs):
                    # 使用整段翻译
                    translated_text = translation_paragraphs[paragraph_idx]
                    paragraph_idx += 1
                    
                    if translated_text:
                        # 获取该块的位置和字体大小
                        if block_lines:
                            first_line = block_lines[0]
                            last_line = block_lines[-1]
                            
                            block_y0 = first_line["y0"]
                            block_y1 = last_line["y1"]
                            block_x0 = first_line["x0"]
                            block_x1 = max(line["x1"] for line in block_lines)
                            avg_font_size = sum(line["font_size"] for line in block_lines) / len(block_lines)
                            
                            # 计算右侧文本框位置（大幅扩展空间）
                            block_height = block_y1 - block_y0
                            right_rect = fitz.Rect(
                                block_x0 + page_width - 20,  # 向左扩展一点
                                block_y0 - block_height * 0.3,  # 向上扩展30%
                                page_width * 2 - 30,  # 扩展到右边距附近
                                block_y1 + block_height * 1.2  # 大幅向下扩展120%
                            )
                            
                            # 使用与原文相同的字体大小（中文稍小一点）
                            font_size = avg_font_size * 0.85
                            
                            try:
                                has_chinese = any('\u4e00' <= c <= '\u9fff' for c in translated_text)
                                
                                current_font = font_size
                                success = False
                                
                                # 尝试多次插入，逐步缩小字体
                                for attempt in range(5):
                                    if has_chinese and font_registered:
                                        result = new_page.insert_textbox(
                                            right_rect,
                                            translated_text,
                                            fontsize=current_font,
                                            fontname="custom_chinese",
                                            color=fitz.utils.getColor("black"),
                                            align=fitz.TEXT_ALIGN_LEFT,
                                        )
                                    else:
                                        result = new_page.insert_textbox(
                                            right_rect,
                                            translated_text,
                                            fontsize=current_font,
                                            color=fitz.utils.getColor("black"),
                                            align=fitz.TEXT_ALIGN_LEFT,
                                        )
                                    
                                    if result >= 0:
                                        success = True
                                        break
                                    
                                    # 缩小字体重试
                                    current_font = max(current_font * 0.85, 6)
                                
                                if not success:
                                    print(f"[DEBUG] Text truncated even after {attempt+1} attempts")
                                    
                            except Exception as e:
                                print(f"[DEBUG] Failed to insert text: {str(e)}")
                                pass
        
        pdf_bytes = doc.write()
        doc.close()
        src_doc.close()
        
        return pdf_bytes
