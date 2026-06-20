import re
from typing import Any, Dict, List

import fitz

from app.services.pdf_layout_utils import block_rect, line_rect
from app.services.pdf_text_utils import (
    HEADING_PUNCTUATION,
    MATH_SYMBOLS,
    SENTENCE_ENDINGS,
    has_emoji,
    is_symbol_emoji,
    is_symbol_emoji_text,
    normalize_pdf_text,
)


class PDFLayoutAnalyzer:
    """Extracts and classifies PDF text blocks before translation/rendering."""
    def _ends_sentence(self, text: str) -> bool:
        clean_text = normalize_pdf_text(text).rstrip()
        if not clean_text:
            return False
        clean_text = clean_text.rstrip(")]}）】》”’\"'")
        return clean_text.endswith(SENTENCE_ENDINGS)

    def _line_is_heading_like(self, line: Dict[str, Any], block_width: float) -> bool:
        text = normalize_pdf_text(line.get("text", ""))
        if not text:
            return False

        rect = line_rect(line)
        font_size = float(line.get("font_size") or 0)
        if font_size <= 0 or block_width <= 0:
            return False

        line_width = rect.width
        word_count = len(re.findall(r"[A-Za-z0-9]+(?:[./:-][A-Za-z0-9]+)*", text))
        short_heading = len(text) <= 90 and word_count <= 12
        compact_heading = line_width <= block_width * 0.92
        ends_like_heading = not self._ends_sentence(text)
        return short_heading and compact_heading and ends_like_heading

    def _first_line_paragraph_indent(
        self,
        lines: List[Dict[str, Any]],
        font_size: float,
    ) -> float:
        line_rects = []
        for line in lines:
            if not normalize_pdf_text(line.get("text", "")):
                continue
            rect = line_rect(line)
            if not rect.is_empty:
                line_rects.append(rect)

        if len(line_rects) < 2:
            return 0.0

        first_line = line_rects[0]
        following_left = min(rect.x0 for rect in line_rects[1:])
        indent = first_line.x0 - following_left
        if indent < max(font_size * 0.45, 4.0):
            return 0.0

        block_width = max(max(rect.x1 for rect in line_rects) - min(rect.x0 for rect in line_rects), 1.0)
        if indent > block_width * 0.22:
            return 0.0

        return indent

    def _should_split_segment(
        self,
        current_line: Dict[str, Any],
        previous_line: Dict[str, Any],
        block_left: float,
        block_width: float,
    ) -> bool:
        current_rect = line_rect(current_line)
        previous_rect = line_rect(previous_line)
        current_text = normalize_pdf_text(current_line.get("text", ""))
        previous_text = normalize_pdf_text(previous_line.get("text", ""))
        current_font = float(current_line.get("font_size") or 0)
        previous_font = float(previous_line.get("font_size") or 0)

        if not current_text or not previous_text:
            return False

        vertical_gap = current_rect.y0 - previous_rect.y1
        previous_indent = max(previous_rect.x0 - block_left, 0)
        current_indent = max(current_rect.x0 - block_left, 0)
        previous_width = previous_rect.width
        punctuation_end = self._ends_sentence(previous_text)
        previous_word_count = len(re.findall(r"[A-Za-z0-9]+(?:[./:-][A-Za-z0-9]+)*", previous_text))

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
            previous_word_count <= 4
            and len(previous_text) <= 42
            and not punctuation_end
            and current_rect.width >= previous_width * 1.6
            and current_indent <= previous_indent + max(current_font * 0.35, 3.0)
        ):
            return True

        if (
            previous_font > 0
            and current_font > 0
            and previous_font >= current_font * 1.06
            and self._line_is_heading_like(previous_line, block_width)
        ):
            return True

        current_starts_like_heading = bool(re.match(r"^[A-Za-z]", current_text))
        if (
            current_starts_like_heading
            and not any(char.isdigit() for char in current_text)
            and current_font > 0
            and self._line_is_heading_like(current_line, block_width)
            and previous_width <= block_width * 0.72
            and not punctuation_end
        ):
            return True

        return False

    def _join_line_texts_for_translation(self, lines: List[Dict[str, Any]]) -> str:
        parts: List[str] = []
        for line in lines:
            text = normalize_pdf_text(line.get("text", ""))
            if not text:
                continue

            if parts and self._should_join_after_line_hyphen(parts[-1], text):
                parts[-1] = f"{parts[-1]}{text}"
            else:
                parts.append(text)

        return " ".join(parts).strip()

    def _should_join_after_line_hyphen(self, previous_text: str, current_text: str) -> bool:
        previous = previous_text.rstrip()
        current = current_text.lstrip()
        if not previous or not current:
            return False

        if previous[-1] not in "-\u2010\u2011\u2012\u2013":
            return False
        if not re.search(r"[A-Za-z0-9]$", previous[:-1]):
            return False
        if not re.match(r"[a-z0-9]", current):
            return False
        return True

    def _build_text_block_payload(
        self,
        lines: List[Dict[str, Any]],
        page_rect: fitz.Rect,
        page_num: int,
    ) -> Dict[str, Any]:
        rect = line_rect(lines[0])
        for line in lines[1:]:
            rect = rect | line_rect(line)

        text = self._join_line_texts_for_translation(lines)
        font_size = max(float(line.get("font_size") or 0) for line in lines)
        first_line_indent = self._first_line_paragraph_indent(lines, font_size)
        block_payload = {
            "type": "text",
            "bbox": {"x0": rect.x0, "y0": rect.y0, "x1": rect.x1, "y1": rect.y1},
            "text": text,
            "font_size": font_size,
            "lines": lines,
            "first_line_indent": first_line_indent,
            "starts_with_paragraph_indent": first_line_indent > 0,
            "page_width": float(page_rect.width),
            "page_height": float(page_rect.height),
            "is_formula": self._is_formula_like_text(text),
        }
        block_payload["is_header_footer_metadata"] = self._is_header_footer_metadata_block(
            block_payload,
            page_rect,
            page_num,
        )
        block_payload["is_attribution_metadata"] = self._is_attribution_metadata_block(
            block_payload,
            page_rect,
            page_num,
        )
        layout_role = self._classify_layout_role(block_payload, page_rect, page_num)
        block_payload["layout_role"] = layout_role
        block_payload["is_metadata"] = layout_role == "metadata"
        block_payload["is_dense_reference"] = layout_role == "dense_reference"
        block_payload["is_marginalia"] = layout_role == "marginalia"
        block_payload["is_vertical_text"] = layout_role == "vertical_text"
        return block_payload

    def _is_publication_metadata_block(self, block: Dict[str, Any], page_rect: fitz.Rect) -> bool:
        rect = block_rect(block)
        clean_text = normalize_pdf_text(block.get("text", ""))
        if not clean_text or rect.is_empty or page_rect.width <= 0 or page_rect.height <= 0:
            return False

        page_width = max(page_rect.width, 1.0)
        page_height = max(page_rect.height, 1.0)
        text_lower = clean_text.lower()
        compact_text = re.sub(r"\s+", "", clean_text)
        font_size = float(block.get("font_size") or 0)
        line_count = len([
            line for line in block.get("lines", [])
            if normalize_pdf_text(line.get("text", ""))
        ])
        width_ratio = rect.width / page_width
        top_band = rect.y0 <= page_height * 0.09
        bottom_band = rect.y1 >= page_height * 0.94
        lower_page_region = rect.y0 >= page_height * 0.72
        side_or_corner = rect.x0 <= page_width * 0.12 or rect.x1 >= page_width * 0.86
        has_url = any(token in text_lower for token in ("www.", "http://", "https://", ".org", ".com", ".edu"))
        has_email = "@" in clean_text and "." in clean_text
        has_open_access = "open access" in text_lower
        has_article_online = "article is online" in text_lower
        has_contact_marker = bool(re.search(r"\b(?:corresponding author|e-?mail|email|doi)\b", text_lower))
        has_metadata_markers = bool(re.search(
            r"\b(?:issn|doi|vol\.?|volume|issue|copyright|published|publisher|license)\b",
            text_lower,
        ))

        if any(marker in text_lower for marker in ("doi:", "copyright", "all rights reserved", "macmillan publishers")):
            return True
        if "\u00a9" in clean_text or text_lower.startswith("(c)"):
            return True
        if bottom_band and font_size <= 7.5 and line_count <= 4:
            return True
        if bottom_band and re.search(r"\b(?:nature|science|cell|volume|vol)\b", text_lower) and len(clean_text) <= 120:
            return True
        if (
            lower_page_region
            and font_size <= 8.5
            and line_count <= 5
            and len(clean_text) <= 320
            and (
                has_url
                or has_email
                or has_open_access
                or has_article_online
                or has_contact_marker
                or has_metadata_markers
            )
        ):
            return True

        letters = [char for char in compact_text if char.isalpha()]
        uppercase_ratio = (
            sum(1 for char in letters if char.isupper()) / max(len(letters), 1)
            if letters
            else 0
        )
        short_label = len(compact_text) <= 32 and line_count <= 2 and width_ratio <= 0.28
        if top_band and short_label and uppercase_ratio >= 0.72:
            return True
        if top_band and side_or_corner and short_label and font_size <= 16:
            return True

        return False

    def _is_attribution_metadata_block(
        self,
        block: Dict[str, Any],
        page_rect: fitz.Rect,
        page_num: int,
    ) -> bool:
        if page_num != 0:
            return False

        rect = block_rect(block)
        clean_text = normalize_pdf_text(block.get("text", ""))
        if not clean_text or rect.is_empty or page_rect.width <= 0 or page_rect.height <= 0:
            return False

        page_width = max(page_rect.width, 1.0)
        page_height = max(page_rect.height, 1.0)
        if rect.y0 < page_height * 0.68:
            return False

        line_texts = [
            normalize_pdf_text(line.get("text", ""))
            for line in block.get("lines", [])
            if normalize_pdf_text(line.get("text", ""))
        ]
        line_count = len(line_texts)
        if line_count == 0 or line_count > 4:
            return False

        font_size = float(block.get("font_size") or 0)
        if font_size > 30:
            return False

        text_lower = clean_text.lower()
        word_count = len(re.findall(r"[A-Za-z0-9][A-Za-z0-9.'@_-]*", clean_text))
        if word_count > 24 or len(clean_text) > 180:
            return False

        width_ratio = rect.width / page_width
        centered_or_compact = (
            width_ratio <= 0.70
            or abs((rect.x0 + rect.x1) / 2 - page_width / 2) <= page_width * 0.28
        )
        if not centered_or_compact:
            return False

        if self._ends_sentence(clean_text):
            return False
        if re.search(r"[.!?;:]\s+[A-Z]", clean_text):
            return False

        has_handle = bool(re.search(r"(?<![\w.])@[A-Za-z0-9_]{2,30}\b", clean_text))
        has_byline = bool(re.match(r"(?i)^(?:by|from|via)\s+(?:@|[A-Z0-9])", clean_text))
        has_credit_role = bool(re.search(
            r"\b(?:author|creator|maker|founder|co[- ]?founder|designer|illustrator|editor)\b",
            text_lower,
        ))
        has_made_by_phrase = bool(re.search(r"\b(?:made|built|written|created|designed)\s+by\b", text_lower))
        has_brand_separator = clean_text.count("+") >= 2 and word_count <= 18
        has_role_separator = clean_text.count("+") >= 1 and bool(re.search(
            r"\b(?:founder|creator|maker|author|designer)\b",
            text_lower,
        ))

        return bool(
            has_handle
            or has_byline
            or has_credit_role
            or has_made_by_phrase
            or has_brand_separator
            or has_role_separator
        )

    def _is_dense_reference_block(self, block: Dict[str, Any], page_rect: fitz.Rect) -> bool:
        rect = block_rect(block)
        clean_text = normalize_pdf_text(block.get("text", ""))
        if not clean_text or rect.is_empty or page_rect.width <= 0 or page_rect.height <= 0:
            return False

        font_size = float(block.get("font_size") or 0)
        lines = [
            line for line in block.get("lines", [])
            if normalize_pdf_text(line.get("text", ""))
        ]
        line_count = len(lines)
        if line_count < 12 or font_size > 7.4:
            return False

        page_height = max(page_rect.height, 1.0)
        height_ratio = rect.height / page_height
        words = re.findall(r"[A-Za-z][A-Za-z.'-]*", clean_text)
        separator_count = sum(clean_text.count(separator) for separator in (",", ";", "|"))
        digit_count = sum(1 for char in clean_text if char.isdigit())
        short_line_count = sum(
            1
            for line in lines
            if len(normalize_pdf_text(line.get("text", ""))) <= 95
        )
        separator_ratio = separator_count / max(len(words), 1)

        if height_ratio >= 0.22 and line_count >= 20:
            return True
        if line_count >= 12 and short_line_count >= line_count * 0.75 and separator_ratio >= 0.18:
            return True
        if line_count >= 16 and digit_count >= line_count and separator_count >= line_count // 2:
            return True

        return False

    def _classify_layout_role(self, block: Dict[str, Any], page_rect: fitz.Rect, page_num: int = 0) -> str:
        rect = block_rect(block)
        if rect.is_empty or page_rect.width <= 0 or page_rect.height <= 0:
            return "body"

        if self._is_publication_metadata_block(block, page_rect):
            return "metadata"
        if block.get("is_attribution_metadata") or self._is_attribution_metadata_block(block, page_rect, page_num):
            return "metadata"
        if self._is_dense_reference_block(block, page_rect):
            return "dense_reference"

        page_width = max(page_rect.width, 1.0)
        page_height = max(page_rect.height, 1.0)
        width_ratio = rect.width / page_width
        height_ratio = rect.height / page_height
        center_x = (rect.x0 + rect.x1) / 2
        in_side_band = center_x <= page_width * 0.14 or center_x >= page_width * 0.86
        narrow_side_block = in_side_band and width_ratio <= 0.18 and height_ratio >= 0.015

        lines = [
            line for line in block.get("lines", [])
            if normalize_pdf_text(line.get("text", ""))
        ]
        line_count = len(lines)
        clean_text = normalize_pdf_text(block.get("text", ""))
        compact_text = re.sub(r"\s+", "", clean_text)
        tall_narrow = rect.height >= max(rect.width * 2.2, 28.0) and width_ratio <= 0.16
        short_line_count = sum(
            1
            for line in lines
            if len(re.sub(r"\s+", "", normalize_pdf_text(line.get("text", "")))) <= 3
        )
        likely_vertical = (
            tall_narrow
            and (
                (
                    line_count >= 2
                    and short_line_count >= max(2, line_count // 2)
                    and len(compact_text) <= max(24, line_count * 4)
                )
                or (
                    in_side_band
                    and line_count == 1
                    and len(compact_text) <= 80
                    and rect.height >= max(rect.width * 6.0, 80.0)
                )
            )
        )

        if likely_vertical:
            return "vertical_text"
        if narrow_side_block:
            return "marginalia"
        return "body"

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
            if any(normalize_pdf_text(line.get("text", "")) for line in lines)
        ]

    def _is_formula_like_text(self, text: str) -> bool:
        clean_text = normalize_pdf_text(text)
        compact_text = "".join(char for char in clean_text if not char.isspace())
        if len(compact_text) < 2:
            return False

        math_symbols = MATH_SYMBOLS
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

        if any(char in compact_text for char in "\u2211\u222b\u221a\u221e\u2248\u2260\u2264\u2265\u00b1\u00d7\u00f7") and letter_count <= len(compact_text) * 0.65:
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
        if is_symbol_emoji_text(block.get("text", "")):
            return False
        if block.get("is_chart_text"):
            return False
        if block.get("layout_role") in {"metadata", "dense_reference", "vertical_text"}:
            return False
        if block.get("is_header_footer_metadata"):
            return False
        return not self._is_formula_like_text(block.get("text", ""))

    def _refine_dense_reference_flags(self, text_blocks: List[Dict[str, Any]], page_rect: fitz.Rect) -> None:
        if page_rect.width <= 0 or page_rect.height <= 0:
            return

        dense_blocks = [
            block for block in text_blocks
            if block.get("layout_role") == "dense_reference"
        ]
        if not dense_blocks:
            return

        dense_area = 0.0
        dense_line_count = 0
        for block in dense_blocks:
            rect = block_rect(block)
            dense_area += max(rect.get_area(), 0)
            dense_line_count += len([
                line for line in block.get("lines", [])
                if normalize_pdf_text(line.get("text", ""))
            ])

        page_area = max(page_rect.get_area(), 1.0)
        page_is_dense_reference = dense_area / page_area >= 0.18 or dense_line_count >= 40
        if not page_is_dense_reference:
            return

        for block in text_blocks:
            if block.get("type") != "text":
                continue
            if block.get("layout_role") in {"metadata", "dense_reference"}:
                continue

            rect = block_rect(block)
            font_size = float(block.get("font_size") or 0)
            clean_text = normalize_pdf_text(block.get("text", ""))
            if not clean_text or rect.is_empty:
                continue

            line_count = len([
                line for line in block.get("lines", [])
                if normalize_pdf_text(line.get("text", ""))
            ])
            if font_size <= 7.4 and (line_count <= 8 or rect.height / max(page_rect.height, 1.0) <= 0.16):
                block["layout_role"] = "dense_reference"
                block["is_dense_reference"] = True
                block["is_metadata"] = False
                block["is_marginalia"] = False
                block["is_vertical_text"] = False

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
        clean_text = normalize_pdf_text(block.get("text", ""))
        if not clean_text:
            return False

        line_count = len([
            line for line in block.get("lines", [])
            if normalize_pdf_text(line.get("text", ""))
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
        numeric_token_count = len(re.findall(r"\b\d+(?:[.,]\d+)?[A-Za-z%]*\b", clean_text))
        sentence_like_count = len(re.findall(r"\b[a-z]{4,}\b", clean_text))

        if font_size <= 9.0 and re.fullmatch(r"[A-Za-z]", compact_text):
            return True

        if font_size <= 6.1 and len(clean_text) <= 8 and digit_count >= 1:
            return True
        if font_size <= 6.3 and word_count >= 10 and rect.height <= 28:
            return True
        if (
            allow_multiline
            and font_size <= 7.4
            and line_count >= 6
            and numeric_token_count >= max(8, line_count)
            and sentence_like_count <= word_count * 0.35
        ):
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
            rect = block_rect(block)
            cached_rects.append(rect)
            cached_fonts.append(self._font_size_for_merge(block, rect))
            block["is_chart_text"] = False

        for index, block in enumerate(text_blocks):
            if block.get("type") != "text" or block.get("is_formula") or block.get("is_header_footer_metadata"):
                continue

            rect = cached_rects[index]
            font_size = cached_fonts[index]
            clean_text = normalize_pdf_text(block.get("text", ""))
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
        return is_symbol_emoji(char)

    def _split_marker_prefix(self, text: str):
        clean_text = normalize_pdf_text(text)
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

        marker = "".join(marker_chars) or "\u2022"
        return marker, clean_text[index:].strip(), True

    def _is_header_footer_metadata_block(
        self,
        block: Dict[str, Any],
        page_rect: fitz.Rect,
        page_num: int = 0,
    ) -> bool:
        if block.get("type") != "text" or block.get("is_formula"):
            return False

        rect = block_rect(block)
        if rect.is_empty or rect.width <= 0 or rect.height <= 0 or page_rect.height <= 0:
            return False

        top_band = max(36.0, page_rect.height * 0.08)
        bottom_band = max(42.0, page_rect.height * 0.08)
        in_top_band = rect.y0 <= top_band
        in_bottom_band = rect.y1 >= page_rect.height - bottom_band

        clean_text = normalize_pdf_text(block.get("text", ""))
        if not clean_text:
            return False

        text_lower = clean_text.lower()
        text_no_space = re.sub(r"\s+", "", clean_text)
        has_url = any(token in text_lower for token in ("www.", "http://", "https://", ".org", ".com", ".edu"))
        has_email = "@" in clean_text and "." in clean_text
        page_number_only = text_no_space.isdigit() and len(text_no_space) <= 6
        has_metadata_markers = bool(re.search(r"\b(?:issn|doi|vol\.?|volume|issue|copyright)\b", clean_text, re.IGNORECASE))
        has_publisher_marker = "published by" in text_lower
        has_copyright_marker = "\u00a9" in clean_text or "(c)" in text_lower
        has_open_access = "open access" in text_lower
        has_article_online = "article is online" in text_lower
        has_contact_marker = bool(re.search(r"\b(?:corresponding author|e-?mail|email)\b", text_lower))
        has_volume_page_pattern = bool(re.search(r"\b\d{1,3}\s*:\s*\d{2,6}(?:\s*[-\u2013\u2014]\s*\d{2,6})?\b", clean_text))
        font_size = float(block.get("font_size") or 0)
        line_texts = [
            normalize_pdf_text(line.get("text", ""))
            for line in block.get("lines", [])
            if normalize_pdf_text(line.get("text", ""))
        ]
        line_count = len(line_texts)
        lower_page_region = rect.y0 >= page_rect.height * 0.72
        strong_lower_metadata = (
            lower_page_region
            and font_size <= 8.5
            and line_count <= 5
            and len(clean_text) <= 320
            and (
                has_url
                or has_email
                or has_open_access
                or has_article_online
                or has_contact_marker
                or has_metadata_markers
            )
        )
        strong_bottom_metadata = (
            in_bottom_band and
            (
                has_publisher_marker or
                has_copyright_marker or
                has_metadata_markers or
                (has_url and has_volume_page_pattern)
            )
        )

        if strong_bottom_metadata or strong_lower_metadata:
            return True

        if not (in_top_band or in_bottom_band):
            return False

        if line_count == 0 or line_count > 4 or len(clean_text) > 120:
            return False

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

        if in_top_band and page_num == 0 and not page_label_like:
            return False

        if has_url or has_email or has_metadata_markers or page_number_only:
            return True

        if in_bottom_band:
            if line_count <= 3 and word_count <= 10 and mostly_digits:
                return True
            bottom_position_like = centered_block or near_left_edge or near_right_edge or width_ratio <= 0.55
            if (
                bottom_position_like
                and line_count <= 3
                and word_count <= 8
                and not has_sentence_punctuation
                and not looks_sentence_like
            ):
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

            rect = block_rect(block)
            font_size = self._font_size_for_merge(block, rect)
            if font_size <= 0:
                continue

            block_width = max(rect.width, 1.0)
            block_lines = [
                line for line in block.get("lines", [])
                if normalize_pdf_text(line.get("text", ""))
            ]
            clean_text = normalize_pdf_text(block.get("text", ""))
            word_count = len(re.findall(r"[A-Za-z0-9]+(?:[./:-][A-Za-z0-9]+)*", clean_text))
            heading_like = (
                len(block_lines) == 1
                and len(clean_text) <= 90
                and word_count <= 12
                and not self._ends_sentence(clean_text)
            )
            if not heading_like:
                continue

            for other_index, other in enumerate(text_blocks):
                if other_index == index:
                    continue
                if other.get("type") != "text" or other.get("is_formula"):
                    continue

                other_rect = block_rect(other)
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
        text = normalize_pdf_text(block.get("text", ""))
        if not text:
            return False

        marker, heading_text, saw_marker = self._split_marker_prefix(text)
        if not saw_marker:
            return False

        line_count = len([
            line for line in block.get("lines", [])
            if normalize_pdf_text(line.get("text", ""))
        ])
        if line_count > 2:
            return False

        rect = block_rect(block)
        font_size = self._font_size_for_merge(block, rect)
        if len(heading_text) > 60:
            return False
        if any(char in heading_text for char in HEADING_PUNCTUATION) and len(heading_text) > 20:
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
        if previous.get("is_header_footer_metadata") or current.get("is_header_footer_metadata"):
            return False
        if previous.get("layout_role", "body") != current.get("layout_role", "body"):
            return False
        previous_column = previous.get("layout_column")
        current_column = current.get("layout_column")
        if previous_column is not None and current_column is not None and previous_column != current_column:
            return False
        if self._is_marker_heading(previous) or self._is_marker_heading(current):
            return False

        previous_rect = block_rect(previous)
        current_rect = block_rect(current)
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

        horizontal_overlap = min(previous_rect.x1, current_rect.x1) - max(previous_rect.x0, current_rect.x0)
        min_width = max(min(previous_rect.width, current_rect.width), 1.0)
        if horizontal_overlap < min_width * 0.45:
            return False

        previous_text = normalize_pdf_text(previous.get("text", ""))
        current_text = normalize_pdf_text(current.get("text", ""))
        previous_lines = [
            line for line in previous.get("lines", [])
            if normalize_pdf_text(line.get("text", ""))
        ]
        current_lines = [
            line for line in current.get("lines", [])
            if normalize_pdf_text(line.get("text", ""))
        ]
        punctuation_end = self._ends_sentence(previous_text)
        current_indent = current_rect.x0 - min(previous_rect.x0, current_rect.x0)
        previous_width = previous_rect.width
        combined_width = max(previous_rect.x1, current_rect.x1) - min(previous_rect.x0, current_rect.x0)
        previous_last_line = previous_lines[-1] if previous_lines else None
        if current.get("starts_with_paragraph_indent"):
            current_indent = float(current.get("first_line_indent") or 0.0)
            if current_indent >= max(current_font_size * 0.45, 4.0):
                return False

        if current_lines:
            current_first_text = normalize_pdf_text(current_lines[0].get("text", ""))
            current_starts_like_heading = bool(re.match(r"^[A-Za-z]", current_first_text))
            current_heading_like = self._line_is_heading_like(current_lines[0], combined_width)
            previous_heading_like = bool(previous_lines and self._line_is_heading_like(previous_lines[-1], combined_width))
            previous_first_text = normalize_pdf_text(previous_lines[-1].get("text", "")) if previous_lines else ""
            previous_starts_like_heading = bool(re.match(r"^[A-Za-z]", previous_first_text))
            previous_short_label = (
                previous_starts_like_heading
                and len(previous_first_text) <= 90
                and len(re.findall(r"[A-Za-z0-9]+(?:[./:-][A-Za-z0-9]+)*", previous_first_text)) <= 12
                and not self._ends_sentence(previous_first_text)
            )
            if (
                current_starts_like_heading
                and previous_starts_like_heading
                and current_heading_like
                and (previous_heading_like or previous_short_label)
                and vertical_gap >= max(current_font_size * 0.25, 2.0)
            ):
                return False
            if (
                current_starts_like_heading
                and not any(char.isdigit() for char in current_first_text)
                and current_heading_like
                and previous_width <= combined_width * 0.72
                and not punctuation_end
            ):
                return False

        if (
            previous_lines
            and current_lines
            and previous_font_size >= current_font_size * 1.03
            and (
                previous_width <= combined_width * 0.88
                or self._line_is_heading_like(previous_lines[-1], combined_width)
            )
            and len(previous_lines) == 1
            and not punctuation_end
        ):
            return False

        if (
            punctuation_end
            and current_rect.x0 - previous_rect.x0 >= max(current_font_size * 0.7, 7.5)
        ):
            return False

        if punctuation_end and vertical_gap >= max(previous_font_size * 0.45, 5.0):
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
        previous_rect = block_rect(previous)
        current_rect = block_rect(current)
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
        merged["first_line_indent"] = previous.get("first_line_indent", 0.0)
        merged["starts_with_paragraph_indent"] = bool(previous.get("starts_with_paragraph_indent"))
        merged["merged_blocks"] = previous.get("merged_blocks", 1) + current.get("merged_blocks", 1)
        merged["is_header_footer_metadata"] = (
            previous.get("is_header_footer_metadata", False) or
            current.get("is_header_footer_metadata", False)
        )
        merged["layout_role"] = previous.get("layout_role", current.get("layout_role", "body"))
        if previous.get("layout_column") == current.get("layout_column"):
            merged["layout_column"] = previous.get("layout_column")
        else:
            merged.pop("layout_column", None)
        merged["is_metadata"] = bool(previous.get("is_metadata") or current.get("is_metadata"))
        merged["is_attribution_metadata"] = bool(
            previous.get("is_attribution_metadata") or current.get("is_attribution_metadata")
        )
        merged["is_dense_reference"] = bool(previous.get("is_dense_reference") or current.get("is_dense_reference"))
        merged["is_marginalia"] = bool(previous.get("is_marginalia") or current.get("is_marginalia"))
        merged["is_vertical_text"] = bool(previous.get("is_vertical_text") or current.get("is_vertical_text"))
        return merged

    def _page_width_for_column_detection(self, text_blocks: List[Dict[str, Any]]) -> float:
        widths = [
            float(block.get("page_width") or 0)
            for block in text_blocks
            if float(block.get("page_width") or 0) > 0
        ]
        if widths:
            return max(widths)

        right_edges = []
        for block in text_blocks:
            try:
                right_edges.append(block_rect(block).x1)
            except Exception:
                continue
        return max(right_edges or [0.0])

    def _assign_layout_columns(self, text_blocks: List[Dict[str, Any]]) -> None:
        page_width = self._page_width_for_column_detection(text_blocks)
        if page_width <= 0:
            return

        body_blocks: List[Dict[str, Any]] = []
        for block in text_blocks:
            block.pop("layout_column", None)
            if block.get("type") != "text":
                continue
            if block.get("layout_role", "body") != "body":
                continue
            if block.get("is_header_footer_metadata") or block.get("is_formula"):
                continue

            rect = block_rect(block)
            if rect.is_empty or rect.width <= 0 or rect.height <= 0:
                continue
            if rect.width >= page_width * 0.68:
                continue
            body_blocks.append(block)

        if len(body_blocks) < 4:
            return

        centers = sorted(
            (
                ((block_rect(block).x0 + block_rect(block).x1) / 2, block)
                for block in body_blocks
            ),
            key=lambda item: item[0],
        )
        widths = sorted(max(block_rect(block).width, 1.0) for _, block in centers)
        median_width = widths[len(widths) // 2] if widths else 1.0
        gap_threshold = max(page_width * 0.10, median_width * 0.45, 28.0)

        clusters: List[List[Dict[str, Any]]] = []
        current_cluster: List[Dict[str, Any]] = []
        previous_center = None
        for center, block in centers:
            if previous_center is not None and center - previous_center > gap_threshold and current_cluster:
                clusters.append(current_cluster)
                current_cluster = []
            current_cluster.append(block)
            previous_center = center
        if current_cluster:
            clusters.append(current_cluster)

        clusters = [cluster for cluster in clusters if len(cluster) >= 2]
        if len(clusters) < 2 or len(clusters) > 4:
            return

        column_bands = []
        for cluster in clusters:
            cluster_rect = block_rect(cluster[0])
            for block in cluster[1:]:
                cluster_rect = cluster_rect | block_rect(block)
            column_bands.append(cluster_rect)

        column_bands.sort(key=lambda rect: rect.x0)
        for left, right in zip(column_bands, column_bands[1:]):
            if left.x1 > right.x0 + page_width * 0.08:
                return

        split_points = [
            (column_bands[index].x1 + column_bands[index + 1].x0) / 2
            for index in range(len(column_bands) - 1)
        ]

        for block in text_blocks:
            if block.get("type") != "text" or block.get("layout_role", "body") != "body":
                continue
            if block.get("is_header_footer_metadata") or block.get("is_formula"):
                continue

            rect = block_rect(block)
            if rect.is_empty or rect.width <= 0:
                continue
            if rect.width >= page_width * 0.68:
                block["layout_column"] = -1
                continue
            if any(rect.x0 < split_point < rect.x1 for split_point in split_points):
                block["layout_column"] = -1
                continue

            center = (rect.x0 + rect.x1) / 2
            column_index = 0
            for split_point in split_points:
                if center > split_point:
                    column_index += 1
            block["layout_column"] = column_index

    def _sort_text_blocks_for_merge(self, text_blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        sortable_blocks = [dict(block) for block in text_blocks]
        self._assign_layout_columns(sortable_blocks)

        role_order = {
            "vertical_text": 2,
            "marginalia": 3,
        }

        def sort_key(block: Dict[str, Any]):
            rect = block_rect(block)
            if block.get("is_header_footer_metadata"):
                return (4, rect.y0, rect.x0)
            role = block.get("layout_role", "body")
            if role != "body":
                return (role_order.get(role, 5), rect.y0, rect.x0)

            column = block.get("layout_column")
            if column == -1:
                return (0, rect.y0, rect.x0)
            if column is not None:
                return (1, int(column), rect.y0, rect.x0)
            return (0, rect.y0, rect.x0)

        return sorted(sortable_blocks, key=sort_key)

    def _merge_text_blocks(self, text_blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        merged_blocks = []
        for block in self._sort_text_blocks_for_merge(text_blocks):
            if merged_blocks and self._can_merge_text_blocks(merged_blocks[-1], block):
                merged_blocks[-1] = self._merge_two_text_blocks(merged_blocks[-1], block)
            else:
                merged_blocks.append(dict(block))
        return merged_blocks

