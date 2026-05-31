import fitz
import os
import uuid
from typing import List, Dict, Any


class PDFService:
    def __init__(self):
        self.upload_dir = os.path.join(os.path.dirname(__file__), "..", "..", "uploads")
        self.output_dir = os.path.join(os.path.dirname(__file__), "..", "..", "outputs")
        os.makedirs(self.upload_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)
    
    def save_uploaded_file(self, file_content: bytes) -> str:
        file_id = str(uuid.uuid4())
        file_path = os.path.join(self.upload_dir, f"{file_id}.pdf")
        with open(file_path, "wb") as f:
            f.write(file_content)
        return file_id
    
    def get_file_path(self, file_id: str) -> str:
        return os.path.join(self.upload_dir, f"{file_id}.pdf")
    
    def get_output_path(self, task_id: str) -> str:
        return os.path.join(self.output_dir, f"{task_id}.json")
    
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
                text_blocks.append({
                    "type": "text",
                    "bbox": {"x0": block_x0, "y0": block_y0, "x1": block_x1, "y1": block_y1},
                    "text": block_text.strip(),
                    "font_size": block_font_size,
                    "lines": block_lines,
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
        output_path = self.get_output_path(task_id)
        import json
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    
    def load_translation_result(self, task_id: str) -> Dict[str, Any]:
        output_path = self.get_output_path(task_id)
        if not os.path.exists(output_path):
            raise FileNotFoundError("Result not found")
        
        import json
        with open(output_path, "r", encoding="utf-8") as f:
            return json.load(f)

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

    def _block_rect(self, block: Dict[str, Any]) -> fitz.Rect:
        bbox = block.get("bbox", {})
        return fitz.Rect(bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"])

    def _is_marker_heading(self, block: Dict[str, Any]) -> bool:
        text = self._normalize_pdf_text(block.get("text", ""))
        if not text:
            return False
        return text[0] in ["\U0001F4A1", "\U0001F6E0", "\U0001F680", "\U0001F331"]

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

    def _is_translation_marker_line(self, line: str) -> bool:
        text = self._normalize_pdf_text(line)
        return bool(text) and text[0] in ["\U0001F4A1", "\U0001F6E0", "\U0001F680", "\U0001F331"]

    def _split_page_translation_sections(self, translated_text: str) -> List[List[str]]:
        sections = []
        current_lines = []

        for line in (translated_text or "").splitlines():
            clean_line = self._normalize_pdf_text(line)
            if not clean_line or clean_line in ["/", "\\", "|", "-"]:
                if current_lines and not self._is_translation_marker_line(current_lines[0]):
                    sections.append(current_lines)
                    current_lines = []
                continue

            if self._is_translation_marker_line(clean_line):
                if current_lines:
                    sections.append(current_lines)
                current_lines = [clean_line]
                continue

            current_lines.append(clean_line)

        if current_lines:
            sections.append(current_lines)

        return sections

    def _assign_translation_to_body_blocks(self, body_blocks: List[Dict[str, Any]], body_parts: List[str]):
        if not body_blocks or not body_parts:
            return

        if len(body_blocks) == 1:
            body_blocks[0]["translatedText"] = "\n".join(body_parts)
            return

        for index, block in enumerate(body_blocks):
            if index < len(body_parts):
                block["translatedText"] = body_parts[index]

        if len(body_parts) > len(body_blocks):
            body_blocks[-1]["translatedText"] = "\n".join(
                [body_blocks[-1].get("translatedText", "")] + body_parts[len(body_blocks):]
            ).strip()

    def _apply_page_level_translations(
        self,
        text_blocks: List[Dict[str, Any]],
        translated_text: str,
    ) -> List[Dict[str, Any]]:
        sections = self._split_page_translation_sections(translated_text)
        if not sections:
            return text_blocks

        updated_blocks = [dict(block) for block in text_blocks]
        marker_indices = [
            index for index, block in enumerate(updated_blocks)
            if self._is_marker_heading(block)
        ]
        has_translation_markers = any(
            self._is_translation_marker_line(section[0])
            for section in sections
        )
        if marker_indices and not has_translation_markers:
            return updated_blocks

        block_index = 0
        section_index = 0

        while (
            section_index < len(sections)
            and not self._is_translation_marker_line(sections[section_index][0])
            and block_index < len(updated_blocks)
        ):
            if not self._is_marker_heading(updated_blocks[block_index]):
                updated_blocks[block_index]["translatedText"] = "\n".join(sections[section_index])
                section_index += 1
            block_index += 1

        for marker_position, marker_index in enumerate(marker_indices):
            while (
                section_index < len(sections)
                and not self._is_translation_marker_line(sections[section_index][0])
            ):
                section_index += 1

            if section_index >= len(sections):
                break

            section_lines = sections[section_index]
            updated_blocks[marker_index]["translatedText"] = section_lines[0]
            next_marker_index = (
                marker_indices[marker_position + 1]
                if marker_position + 1 < len(marker_indices)
                else len(updated_blocks)
            )
            body_blocks = [
                block for block in updated_blocks[marker_index + 1:next_marker_index]
                if not self._is_marker_heading(block)
            ]
            self._assign_translation_to_body_blocks(body_blocks, section_lines[1:])
            section_index += 1

        return updated_blocks

    def _color_from_int(self, color: int):
        return (
            ((color >> 16) & 255) / 255,
            ((color >> 8) & 255) / 255,
            (color & 255) / 255,
        )

    def _rect_overlap_ratio(self, first: fitz.Rect, second: fitz.Rect) -> float:
        overlap = first & second
        if overlap.is_empty or first.get_area() <= 0:
            return 0
        return overlap.get_area() / first.get_area()

    def _get_block_style(self, page, rect: fitz.Rect, fallback_font_size: float = 10) -> Dict[str, Any]:
        sizes = []
        color_weights = {}
        fonts = []

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
                    sizes.append(span.get("size", fallback_font_size))
                    color_weights[color] = color_weights.get(color, 0) + max(len(span_text), 1)
                    fonts.append(span.get("font", ""))

        if sizes:
            sorted_sizes = sorted(sizes)
            font_size = sorted_sizes[len(sorted_sizes) // 2]
        else:
            font_size = fallback_font_size

        dominant_color = max(color_weights, key=color_weights.get) if color_weights else 0
        color = self._color_from_int(dominant_color) if color_weights else fitz.utils.getColor("black")
        font_name = fonts[0] if fonts else ""

        return {
            "font_size": max(font_size, 6),
            "color": color,
            "font_name": font_name,
        }

    def _split_leading_marker(self, translated_text: str, source_text: str):
        marker_chars = ["\U0001F4A1", "\U0001F6E0", "\U0001F680", "\U0001F331"]
        translated = self._normalize_pdf_text(translated_text)
        source = self._normalize_pdf_text(source_text)

        marker = ""
        for candidate in marker_chars:
            if translated.startswith(candidate):
                marker = candidate
                translated = translated[len(candidate):].strip()
                break

        if not marker:
            for candidate in marker_chars:
                if source.startswith(candidate):
                    marker = candidate
                    break

        return marker, translated

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
                baseline = rect.y0 + current_size
                for line in lines:
                    page.insert_text(
                        (rect.x0, baseline),
                        line,
                        fontsize=current_size,
                        fontname=font_name,
                        color=color,
                    )
                    baseline += line_step
                return True

            current_size *= 0.9

        return False
    
    def generate_translated_pdf(self, file_id: str, translation_result: Dict[str, Any]) -> bytes:
        input_path = self.get_file_path(file_id)
        if not os.path.exists(input_path):
            raise FileNotFoundError("File not found")
        
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
        
        pdf_bytes = doc.write()
        doc.close()
        
        return pdf_bytes

    def generate_bilingual_pdf(self, file_id: str, translation_result: Dict[str, Any]) -> bytes:
        input_path = self.get_file_path(file_id)
        if not os.path.exists(input_path):
            raise FileNotFoundError("File not found")

        src_doc = fitz.open(input_path)
        doc = fitz.open()

        chinese_font_path = self._find_existing_font([
            "C:\\Windows\\Fonts\\simhei.ttf",
            "C:\\Windows\\Fonts\\msyh.ttc",
            "C:\\Windows\\Fonts\\simkai.ttf",
        ])
        emoji_font_path = self._find_existing_font([
            "C:\\Windows\\Fonts\\seguiemj.ttf",
            "C:\\Windows\\Fonts\\seguisym.ttf",
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
            new_page.draw_rect(
                right_bg_rect,
                color=fitz.utils.getColor("white"),
                fill=fitz.utils.getColor("white"),
            )
            new_page.draw_line(
                (page_width, 0),
                (page_width, original_rect.height),
                color=fitz.utils.getColor("gray"),
                width=1.0,
            )

            font_registered = False
            if chinese_font_path:
                try:
                    new_page.insert_font(fontfile=chinese_font_path, fontname="custom_chinese")
                    font_registered = True
                except Exception as e:
                    print(f"[DEBUG] Failed to register font: {str(e)}")

            emoji_registered = False
            if emoji_font_path:
                try:
                    new_page.insert_font(fontfile=emoji_font_path, fontname="custom_emoji")
                    emoji_registered = True
                except Exception as e:
                    print(f"[DEBUG] Failed to register emoji font: {str(e)}")

            text_font_name = "custom_chinese" if font_registered else "helv"
            emoji_font_name = "custom_emoji" if emoji_registered else text_font_name
            text_measure_font = fitz.Font(fontfile=chinese_font_path) if font_registered else fitz.Font("helv")
            emoji_measure_font = fitz.Font(fontfile=emoji_font_path) if emoji_registered else text_measure_font
            text_blocks = [
                block for block in page_data.get("textBlocks", [])
                if block.get("type") == "text" and block.get("translatedText")
            ]
            text_blocks = self._merge_text_blocks(text_blocks)
            text_blocks = self._apply_page_level_translations(text_blocks, page_data.get("translated", ""))

            for index, block in enumerate(text_blocks):
                bbox = block.get("bbox", {})
                try:
                    source_rect = fitz.Rect(bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"])
                except Exception:
                    continue

                if source_rect.is_empty or source_rect.width <= 0 or source_rect.height <= 0:
                    continue

                translated_text = self._normalize_pdf_text(block.get("translatedText", ""))
                source_text = self._normalize_pdf_text(block.get("text", ""))
                marker, content_text = self._split_leading_marker(translated_text, source_text)
                if not content_text:
                    content_text = translated_text

                style = self._get_block_style(src_page, source_rect, block.get("font_size") or 10)
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

                right_rect = fitz.Rect(
                    page_width + source_rect.x0,
                    max(0, source_rect.y0 - 1),
                    min(page_width * 2 - 24, page_width + source_rect.x1 + 2),
                    min(original_rect.height - 12, target_bottom),
                )
                if right_rect.width < base_font_size * 2:
                    right_rect.x1 = min(page_width * 2 - 24, right_rect.x0 + base_font_size * 4)

                text_rect = right_rect
                if marker:
                    marker_width = base_font_size * 1.35
                    marker_rect = fitz.Rect(
                        right_rect.x0,
                        right_rect.y0,
                        min(right_rect.x1, right_rect.x0 + marker_width),
                        right_rect.y1,
                    )
                    new_page.draw_circle(
                        (
                            max(page_width + 4, right_rect.x0 - base_font_size * 0.65),
                            right_rect.y0 + base_font_size * 0.58,
                        ),
                        max(base_font_size * 0.08, 1.1),
                        color=fitz.utils.getColor("black"),
                        fill=fitz.utils.getColor("black"),
                    )

                    copied_marker_width = self._copy_source_marker(
                        new_page,
                        src_doc,
                        page_num,
                        source_rect,
                        marker_rect,
                        base_font_size,
                    )
                    if copied_marker_width <= 0:
                        self._insert_fitted_textbox(
                            new_page,
                            marker_rect,
                            marker,
                            emoji_font_name,
                            base_font_size * 0.9,
                            fitz.utils.getColor("black"),
                            measure_font=emoji_measure_font,
                        )

                    text_rect = fitz.Rect(
                        min(right_rect.x1, right_rect.x0 + marker_width),
                        right_rect.y0,
                        right_rect.x1,
                        right_rect.y1,
                    )

                try:
                    line_height = 1.36 if self._has_cjk(content_text) else 1.2
                    success = self._insert_fitted_textbox(
                        new_page,
                        text_rect,
                        content_text,
                        text_font_name,
                        base_font_size,
                        style["color"],
                        line_height=line_height,
                        measure_font=text_measure_font,
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
                            line_height=line_height,
                            measure_font=text_measure_font,
                        )
                except Exception as e:
                    print(f"[DEBUG] Failed to insert text: {str(e)}")

        pdf_bytes = doc.write()
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
