import fitz
import os
import re
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

    PREVIEW_VISUAL_LAYER_SCALE = 1.25

    def get_file_storage_key(self, file_id: str) -> str:
        return f"uploads/{file_id}.pdf"

    def get_output_storage_key(self, task_id: str) -> str:
        return f"outputs/{task_id}.json"

    def get_output_page_storage_key(self, task_id: str, page_num: int) -> str:
        return f"outputs/{task_id}/pages/{page_num + 1}.json"

    def get_export_pdf_storage_key(self, task_id: str, output_type: str) -> str:
        safe_output_type = "bilingual" if output_type == "bilingual" else "translated"
        return f"outputs/{task_id}/exports/{safe_output_type}.pdf"
    
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

        doc = fitz.open(file_path)
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
        
        # 使用 get_text("dict") 获取完整的文本信息，包括字体详情
        text_info = page.get_text("dict")
        graphic_regions = self._collect_graphic_regions(page, text_info)
        
        for block in text_info.get("blocks", []):
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
                if line_text_parts:
                    line_text = " ".join(line_text_parts)
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
        self._refine_header_footer_metadata_flags(text_blocks)
        self._mark_chart_text_blocks(text_blocks, page_rect, graphic_regions)
        
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
    
    def load_translation_result(self, task_id: str) -> Dict[str, Any]:
        storage_key = self.get_output_storage_key(task_id)
        if not storage_service.exists(storage_key):
            raise FileNotFoundError("Result not found")
        
        import json
        return json.loads(storage_service.read_bytes(storage_key).decode("utf-8"))

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

    def has_cached_export_pdf(self, task_id: str, output_type: str) -> bool:
        return storage_service.exists(self.get_export_pdf_storage_key(task_id, output_type))

    def get_cached_export_pdf_path(self, task_id: str, output_type: str) -> str:
        return storage_service.get_local_path(self.get_export_pdf_storage_key(task_id, output_type))

    def load_cached_export_pdf(self, task_id: str, output_type: str) -> bytes:
        return storage_service.read_bytes(self.get_export_pdf_storage_key(task_id, output_type))

    def save_cached_export_pdf(self, task_id: str, output_type: str, pdf_bytes: bytes) -> None:
        storage_service.save_bytes(self.get_export_pdf_storage_key(task_id, output_type), pdf_bytes)

    def delete_cached_export_pdfs(self, task_id: str) -> None:
        for output_type in ("translated", "bilingual"):
            storage_key = self.get_export_pdf_storage_key(task_id, output_type)
            if storage_service.exists(storage_key):
                storage_service.delete(storage_key)

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

    def _line_rect(self, line: Dict[str, Any]) -> fitz.Rect:
        bbox = line.get("bbox", {})
        return fitz.Rect(bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"])

    def _line_is_heading_like(self, line: Dict[str, Any], block_width: float) -> bool:
        text = self._normalize_pdf_text(line.get("text", ""))
        if not text:
            return False

        rect = self._line_rect(line)
        font_size = float(line.get("font_size") or 0)
        if font_size <= 0 or block_width <= 0:
            return False

        line_width = rect.width
        word_count = len(re.findall(r"[A-Za-z0-9]+(?:[./:-][A-Za-z0-9]+)*", text))
        short_heading = len(text) <= 90 and word_count <= 12
        compact_heading = line_width <= block_width * 0.82
        ends_like_heading = not text.endswith((".", "!", "?", ";", ":", "。", "！", "？", "；", "："))
        return short_heading and compact_heading and ends_like_heading

    def _should_split_segment(
        self,
        current_line: Dict[str, Any],
        previous_line: Dict[str, Any],
        block_left: float,
        block_width: float,
    ) -> bool:
        current_rect = self._line_rect(current_line)
        previous_rect = self._line_rect(previous_line)
        current_text = self._normalize_pdf_text(current_line.get("text", ""))
        previous_text = self._normalize_pdf_text(previous_line.get("text", ""))
        current_font = float(current_line.get("font_size") or 0)
        previous_font = float(previous_line.get("font_size") or 0)

        if not current_text or not previous_text:
            return False

        vertical_gap = current_rect.y0 - previous_rect.y1
        previous_indent = max(previous_rect.x0 - block_left, 0)
        current_indent = max(current_rect.x0 - block_left, 0)
        previous_width = previous_rect.width
        punctuation_end = previous_text.endswith((".", "!", "?", ";", ":", "。", "！", "？", "；", "："))

        if vertical_gap > max(max(previous_font, current_font) * 0.35, 3.2):
            return True

        if (
            current_indent >= max(current_font * 0.7, 7.5)
            and current_indent > previous_indent + max(previous_font * 0.35, 3.0)
            and punctuation_end
        ):
            return True

        if (
            punctuation_end
            and previous_width <= block_width * 0.76
            and current_indent <= max(current_font * 0.3, 3.0)
        ):
            return True

        if (
            previous_font > 0
            and current_font > 0
            and previous_font >= current_font * 1.06
            and self._line_is_heading_like(previous_line, block_width)
        ):
            return True

        return False

    def _build_text_block_payload(
        self,
        lines: List[Dict[str, Any]],
        page_rect: fitz.Rect,
        page_num: int,
    ) -> Dict[str, Any]:
        rect = self._line_rect(lines[0])
        for line in lines[1:]:
            rect = rect | self._line_rect(line)

        text = " ".join(
            self._normalize_pdf_text(line.get("text", ""))
            for line in lines
            if self._normalize_pdf_text(line.get("text", ""))
        ).strip()
        font_size = max(float(line.get("font_size") or 0) for line in lines)
        block_payload = {
            "type": "text",
            "bbox": {"x0": rect.x0, "y0": rect.y0, "x1": rect.x1, "y1": rect.y1},
            "text": text,
            "font_size": font_size,
            "lines": lines,
            "is_formula": self._is_formula_like_text(text),
        }
        block_payload["is_header_footer_metadata"] = self._is_header_footer_metadata_block(
            block_payload,
            page_rect,
            page_num,
        )
        return block_payload

    def _split_text_block_from_lines(
        self,
        block_lines: List[Dict[str, Any]],
        page_rect: fitz.Rect,
        page_num: int,
    ) -> List[Dict[str, Any]]:
        if not block_lines:
            return []

        block_left = min(line["bbox"]["x0"] for line in block_lines)
        block_right = max(line["bbox"]["x1"] for line in block_lines)
        block_width = max(block_right - block_left, 1.0)

        segments: List[List[Dict[str, Any]]] = []
        current_segment: List[Dict[str, Any]] = [block_lines[0]]

        for line in block_lines[1:]:
            previous_line = current_segment[-1]
            if self._should_split_segment(line, previous_line, block_left, block_width):
                segments.append(current_segment)
                current_segment = [line]
            else:
                current_segment.append(line)

        if current_segment:
            segments.append(current_segment)

        return [
            self._build_text_block_payload(lines, page_rect, page_num)
            for lines in segments
            if any(self._normalize_pdf_text(line.get("text", "")) for line in lines)
        ]

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
        if block.get("is_chart_text"):
            return False
        return not self._is_formula_like_text(block.get("text", ""))

    def _collect_graphic_regions(self, page, text_info: Dict[str, Any]) -> List[fitz.Rect]:
        regions: List[fitz.Rect] = []

        for block in text_info.get("blocks", []):
            if block.get("type") == 0:
                continue
            bbox = block.get("bbox")
            if not bbox or len(bbox) != 4:
                continue
            rect = fitz.Rect(*bbox)
            if not rect.is_empty and rect.width > 0 and rect.height > 0:
                regions.append(rect)

        for drawing in page.get_drawings():
            rect = drawing.get("rect")
            if not rect:
                continue
            draw_rect = fitz.Rect(rect)
            if draw_rect.is_empty or draw_rect.width <= 0 or draw_rect.height <= 0:
                continue
            regions.append(draw_rect)

        return self._merge_overlapping_regions(regions, gap=6.0)

    def _merge_overlapping_regions(self, regions: List[fitz.Rect], gap: float = 0.0) -> List[fitz.Rect]:
        merged_regions: List[fitz.Rect] = []

        for region in sorted(regions, key=lambda rect: (rect.y0, rect.x0, rect.y1, rect.x1)):
            current = fitz.Rect(region)
            for index, existing in enumerate(merged_regions):
                expanded_existing = fitz.Rect(
                    existing.x0 - gap,
                    existing.y0 - gap,
                    existing.x1 + gap,
                    existing.y1 + gap,
                )
                if expanded_existing.intersects(current):
                    merged_regions[index] = existing | current
                    break
            else:
                merged_regions.append(current)

        changed = True
        while changed:
            changed = False
            result: List[fitz.Rect] = []
            for region in merged_regions:
                for index, existing in enumerate(result):
                    expanded_existing = fitz.Rect(
                        existing.x0 - gap,
                        existing.y0 - gap,
                        existing.x1 + gap,
                        existing.y1 + gap,
                    )
                    if expanded_existing.intersects(region):
                        result[index] = existing | region
                        changed = True
                        break
                else:
                    result.append(region)
            merged_regions = result

        return merged_regions

    def _is_chart_label_candidate(
        self,
        block: Dict[str, Any],
        rect: fitz.Rect,
        font_size: float,
        *,
        allow_multiline: bool = False,
    ) -> bool:
        clean_text = self._normalize_pdf_text(block.get("text", ""))
        if not clean_text:
            return False

        line_count = len([
            line for line in block.get("lines", [])
            if self._normalize_pdf_text(line.get("text", ""))
        ])
        if not allow_multiline and line_count > 4:
            return False

        compact_text = "".join(char for char in clean_text if not char.isspace())
        word_count = len(re.findall(r"[A-Za-z0-9]+(?:[./:-][A-Za-z0-9]+)*", clean_text))
        digit_count = sum(1 for char in compact_text if char.isdigit())
        letter_count = sum(1 for char in compact_text if char.isalpha())
        uppercase_count = sum(1 for char in compact_text if char.isupper())
        uppercase_ratio = uppercase_count / max(letter_count, 1)
        vertical_label = rect.height > rect.width * 1.8

        if font_size <= 6.1 and len(clean_text) <= 8 and digit_count >= 1:
            return True
        if font_size <= 6.3 and word_count >= 10 and rect.height <= 28:
            return True
        if font_size <= 6.8 and word_count <= 8:
            return True
        if font_size <= 6.8 and digit_count >= max(2, letter_count // 2):
            return True
        if font_size <= 6.8 and uppercase_ratio >= 0.55 and word_count <= 10:
            return True
        if font_size <= 7.2 and vertical_label and len(clean_text) <= 90:
            return True

        return False

    def _mark_chart_text_blocks(
        self,
        text_blocks: List[Dict[str, Any]],
        page_rect: fitz.Rect,
        graphic_regions: List[fitz.Rect],
    ) -> None:
        cached_rects: List[fitz.Rect] = []
        cached_fonts: List[float] = []
        label_candidate_indexes: List[int] = []
        seed_indexes: List[int] = []
        large_graphic_regions = [
            region for region in graphic_regions
            if region.width >= page_rect.width * 0.18 and region.height >= 60
        ]

        for block in text_blocks:
            rect = self._block_rect(block)
            cached_rects.append(rect)
            cached_fonts.append(self._font_size_for_merge(block, rect))
            block["is_chart_text"] = False

        for index, block in enumerate(text_blocks):
            if block.get("type") != "text" or block.get("is_formula") or block.get("is_header_footer_metadata"):
                continue

            rect = cached_rects[index]
            font_size = cached_fonts[index]
            clean_text = self._normalize_pdf_text(block.get("text", ""))
            if not clean_text or rect.is_empty:
                continue

            if self._is_chart_label_candidate(block, rect, font_size, allow_multiline=True):
                label_candidate_indexes.append(index)

            intersects_large_graphic_region = False
            for region in large_graphic_regions:
                expanded_region = fitz.Rect(region.x0 - 6, region.y0 - 6, region.x1 + 6, region.y1 + 6)
                if not expanded_region.intersects(rect):
                    continue
                intersects_large_graphic_region = True
                region_lower_half_start = region.y0 + min(140.0, region.height * 0.45)
                if (
                    self._is_chart_label_candidate(block, rect, font_size, allow_multiline=True)
                    or (font_size <= 7.2 and rect.y0 >= region_lower_half_start and len(clean_text) <= 220)
                ):
                    block["is_chart_text"] = True
                    seed_indexes.append(index)
                    break

            if intersects_large_graphic_region and block["is_chart_text"]:
                continue

        remaining_candidates = [index for index in label_candidate_indexes if not text_blocks[index].get("is_chart_text")]
        candidate_clusters: List[List[int]] = []

        for index in remaining_candidates:
            current_rect = cached_rects[index]
            current_cluster: List[int] = []
            for other_index in remaining_candidates:
                other_rect = cached_rects[other_index]
                expanded_rect = fitz.Rect(
                    current_rect.x0 - 30,
                    current_rect.y0 - 22,
                    current_rect.x1 + 30,
                    current_rect.y1 + 22,
                )
                if expanded_rect.intersects(other_rect):
                    current_cluster.append(other_index)

            if current_cluster:
                candidate_clusters.append(sorted(set(current_cluster)))

        unique_clusters: List[List[int]] = []
        seen_clusters = set()
        for cluster in candidate_clusters:
            cluster_key = tuple(cluster)
            if cluster_key in seen_clusters:
                continue
            seen_clusters.add(cluster_key)
            unique_clusters.append(cluster)

        for cluster in unique_clusters:
            if len(cluster) < 3:
                continue

            cluster_rect = cached_rects[cluster[0]]
            for cluster_index in cluster[1:]:
                cluster_rect = cluster_rect | cached_rects[cluster_index]

            overlaps_large_graphic_region = any(
                fitz.Rect(region.x0 - 12, region.y0 - 12, region.x1 + 12, region.y1 + 12).intersects(cluster_rect)
                for region in large_graphic_regions
            )
            if not (
                len(cluster) >= 4
                or (len(cluster) >= 3 and overlaps_large_graphic_region)
            ):
                continue

            for cluster_index in cluster:
                if not text_blocks[cluster_index].get("is_chart_text"):
                    text_blocks[cluster_index]["is_chart_text"] = True
                    seed_indexes.append(cluster_index)

        changed = True
        while changed:
            changed = False
            for index, block in enumerate(text_blocks):
                if block.get("is_chart_text"):
                    continue
                if block.get("type") != "text" or block.get("is_formula") or block.get("is_header_footer_metadata"):
                    continue

                rect = cached_rects[index]
                font_size = cached_fonts[index]
                if not self._is_chart_label_candidate(block, rect, font_size):
                    continue

                for seed_index in seed_indexes:
                    seed_rect = cached_rects[seed_index]
                    expanded_seed_rect = fitz.Rect(
                        seed_rect.x0 - 36,
                        seed_rect.y0 - 28,
                        seed_rect.x1 + 36,
                        seed_rect.y1 + 28,
                    )
                    if expanded_seed_rect.intersects(rect):
                        block["is_chart_text"] = True
                        seed_indexes.append(index)
                        changed = True
                        break

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

    def _is_header_footer_metadata_block(
        self,
        block: Dict[str, Any],
        page_rect: fitz.Rect,
        page_num: int = 0,
    ) -> bool:
        if block.get("type") != "text" or block.get("is_formula"):
            return False

        rect = self._block_rect(block)
        if rect.is_empty or rect.width <= 0 or rect.height <= 0 or page_rect.height <= 0:
            return False

        top_band = max(36.0, page_rect.height * 0.08)
        bottom_band = max(42.0, page_rect.height * 0.08)
        in_top_band = rect.y0 <= top_band
        in_bottom_band = rect.y1 >= page_rect.height - bottom_band
        if not (in_top_band or in_bottom_band):
            return False

        clean_text = self._normalize_pdf_text(block.get("text", ""))
        if not clean_text:
            return False

        text_lower = clean_text.lower()
        text_no_space = re.sub(r"\s+", "", clean_text)
        has_url = any(token in text_lower for token in ("www.", "http://", "https://", ".org", ".com", ".edu"))
        has_email = "@" in clean_text and "." in clean_text
        page_number_only = text_no_space.isdigit() and len(text_no_space) <= 6
        has_metadata_markers = bool(re.search(r"\b(?:issn|doi|vol\.?|volume|issue|copyright)\b", clean_text, re.IGNORECASE))
        has_publisher_marker = "published by" in text_lower
        has_copyright_marker = "©" in clean_text or "(c)" in text_lower
        has_volume_page_pattern = bool(re.search(r"\b\d{1,3}\s*:\s*\d{2,6}(?:\s*[-–—]\s*\d{2,6})?\b", clean_text))
        strong_bottom_metadata = (
            in_bottom_band and
            (
                has_publisher_marker or
                has_copyright_marker or
                has_metadata_markers or
                (has_url and has_volume_page_pattern)
            )
        )

        if strong_bottom_metadata:
            return True

        line_texts = [
            self._normalize_pdf_text(line.get("text", ""))
            for line in block.get("lines", [])
            if self._normalize_pdf_text(line.get("text", ""))
        ]
        line_count = len(line_texts)
        if line_count == 0 or line_count > 4 or len(clean_text) > 120:
            return False

        font_size = float(block.get("font_size") or 0)
        if font_size > 14:
            return False

        page_width = max(page_rect.width, 1)
        width_ratio = rect.width / page_width
        near_left_edge = rect.x0 <= page_width * 0.16
        near_right_edge = rect.x1 >= page_width * 0.84
        centered_block = abs((rect.x0 + rect.x1) / 2 - page_width / 2) <= page_width * 0.12
        top_header_like_position = near_left_edge or near_right_edge or centered_block

        words = re.findall(r"[A-Za-z0-9][A-Za-z0-9./:@_-]*", clean_text)
        word_count = len(words)
        mostly_digits = bool(text_no_space) and sum(char.isdigit() for char in text_no_space) >= max(3, len(text_no_space) // 3)
        has_sentence_punctuation = bool(re.search(r"[.!?;:]\s+[A-Z]", clean_text))
        looks_sentence_like = clean_text.endswith((".", "?", "!")) and len(clean_text) > 70
        page_label_like = bool(re.fullmatch(r"(page\s*)?\d{1,4}", text_lower.strip()))

        if has_url or has_email or has_metadata_markers or page_number_only:
            return True

        if in_top_band and page_num == 0:
            return False

        if in_bottom_band:
            if line_count <= 3 and word_count <= 10 and mostly_digits:
                return True
            if line_count <= 3 and word_count <= 8 and not has_sentence_punctuation and not looks_sentence_like:
                return True

        if in_top_band:
            if page_label_like:
                return True
            if (
                top_header_like_position
                and width_ratio <= 0.42
                and font_size <= 11.5
                and line_count <= 2
                and word_count <= 10
                and len(clean_text) <= 70
                and not has_sentence_punctuation
                and not looks_sentence_like
            ):
                return True

        return False

    def _refine_header_footer_metadata_flags(self, text_blocks: List[Dict[str, Any]]) -> None:
        for index, block in enumerate(text_blocks):
            if not block.get("is_header_footer_metadata"):
                continue
            if block.get("type") != "text" or block.get("is_formula"):
                continue

            rect = self._block_rect(block)
            font_size = self._font_size_for_merge(block, rect)
            if font_size <= 0:
                continue

            block_width = max(rect.width, 1.0)
            block_lines = [
                line for line in block.get("lines", [])
                if self._normalize_pdf_text(line.get("text", ""))
            ]
            clean_text = self._normalize_pdf_text(block.get("text", ""))
            word_count = len(re.findall(r"[A-Za-z0-9]+(?:[./:-][A-Za-z0-9]+)*", clean_text))
            heading_like = (
                len(block_lines) == 1
                and len(clean_text) <= 90
                and word_count <= 12
                and not clean_text.endswith((".", "!", "?", ";", ":", "。", "！", "？", "；", "："))
            )
            if not heading_like:
                continue

            for other_index, other in enumerate(text_blocks):
                if other_index == index:
                    continue
                if other.get("type") != "text" or other.get("is_formula"):
                    continue

                other_rect = self._block_rect(other)
                if other_rect.is_empty:
                    continue

                vertical_gap = other_rect.y0 - rect.y1
                same_column = (
                    abs(other_rect.x0 - rect.x0) <= max(font_size * 0.8, 10.0)
                    and min(rect.x1, other_rect.x1) - max(rect.x0, other_rect.x0) >= block_width * 0.45
                )
                if same_column and -1.0 <= vertical_gap <= max(font_size * 1.2, 16.0):
                    block["is_header_footer_metadata"] = False
                    break

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

        previous_text = self._normalize_pdf_text(previous.get("text", ""))
        current_text = self._normalize_pdf_text(current.get("text", ""))
        previous_lines = [
            line for line in previous.get("lines", [])
            if self._normalize_pdf_text(line.get("text", ""))
        ]
        current_lines = [
            line for line in current.get("lines", [])
            if self._normalize_pdf_text(line.get("text", ""))
        ]
        punctuation_end = previous_text.endswith((".", "!", "?", ";", ":", "。", "！", "？", "；", "："))
        current_indent = current_rect.x0 - min(previous_rect.x0, current_rect.x0)
        previous_width = previous_rect.width
        combined_width = max(previous_rect.x1, current_rect.x1) - min(previous_rect.x0, current_rect.x0)
        previous_last_line = previous_lines[-1] if previous_lines else None

        if (
            previous_lines
            and current_lines
            and previous_font_size >= current_font_size * 1.06
            and previous_width <= combined_width * 0.82
            and len(previous_lines) == 1
        ):
            return False

        if (
            punctuation_end
            and current_rect.x0 - previous_rect.x0 >= max(current_font_size * 0.7, 7.5)
        ):
            return False

        if (
            punctuation_end
            and previous_width <= combined_width * 0.76
            and previous_last_line is not None
            and current_rect.x0 <= previous_rect.x0 + max(current_font_size * 0.3, 3.0)
        ):
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
        merged["is_header_footer_metadata"] = (
            previous.get("is_header_footer_metadata", False) or
            current.get("is_header_footer_metadata", False)
        )
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
            # Keep the translation-side background crisp enough for reading while
            # avoiding the very large PDFs caused by 2x full-page rasterization.
            pixmap = source_page.get_pixmap(
                matrix=fitz.Matrix(self.PREVIEW_VISUAL_LAYER_SCALE, self.PREVIEW_VISUAL_LAYER_SCALE),
                alpha=False,
            )
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
        visible_lines = [
            line for line in block.get("lines", [])
            if self._normalize_pdf_text(line.get("text", ""))
        ]
        line_count = len(visible_lines)
        block_font_size = float(block.get("font_size") or 0)
        clean_text = self._normalize_pdf_text(block.get("text", ""))
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
            bottom_padding = (
                min(0.8, span_rect.height * 0.04)
                if compact_heading
                else min(1.4, max(0.7, span_rect.height * 0.08))
            )
            cover_rect = fitz.Rect(
                page_width + span_rect.x0 - 0.6,
                span_rect.y0 - 0.6,
                page_width + span_rect.x1 + 0.6,
                span_rect.y1 + bottom_padding,
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
            and not block.get("is_header_footer_metadata")
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
                and not block.get("is_header_footer_metadata")
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
