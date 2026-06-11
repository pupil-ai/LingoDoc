import re
from typing import Any, Dict, List, Optional


SUSPICIOUS_GLYPHS = {"\ufffd", "\u25a1", "\u25a0", "\u25cc", "\u25fb", "\u25fc"}
SENTENCE_ENDINGS = (".", "!", "?", ";", ":", "\u3002", "\uff01", "\uff1f", "\uff1b", "\uff1a")


def _normalize_token(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _leading_layout_marker(text: str) -> str:
    stripped = (text or "").lstrip()
    marker_match = re.match(
        r"^((?:[\*\u2022\u00b7\-–—]\s+)|(?:\(?[A-Za-z0-9ivxlcdmIVXLCDM]{1,8}[\).]\s+))",
        stripped,
    )
    return marker_match.group(1) if marker_match else ""


def _extract_numeric_symbols(text: str) -> List[str]:
    normalized = text or ""
    patterns = [
        r"[<>≤≥]\s*\d+(?:[.,]\d+)?\s*%?",
        r"\d+(?:[.,]\d+)?\s*%",
        r"\d+(?:[.,]\d+)?\s*[–—-]\s*\d+(?:[.,]\d+)?\s*%?",
    ]
    tokens: List[str] = []
    for pattern in patterns:
        for match in re.findall(pattern, normalized):
            token = _normalize_token(match)
            if token and token not in tokens:
                tokens.append(token)
    return tokens[:24]


def _count_suspicious_glyphs(text: str) -> int:
    suspicious = sum(text.count(glyph) for glyph in SUSPICIOUS_GLYPHS)
    question_count = text.count("?")
    if question_count >= 6 and question_count / max(len(text), 1) >= 0.03:
        suspicious += question_count
    return suspicious


def _looks_numeric_or_formula_like(text: str) -> bool:
    clean_text = text or ""
    compact_text = "".join(char for char in clean_text if not char.isspace())
    if len(compact_text) < 2:
        return False

    digit_count = sum(1 for char in compact_text if char.isdigit())
    operator_count = sum(1 for char in compact_text if char in "+-*/=<>^_%")
    letter_count = sum(1 for char in compact_text if char.isalpha())
    word_count = len(re.findall(r"[A-Za-z]+", clean_text))
    numeric_token_count = len(re.findall(r"\b\d+(?:[.,]\d+)?[A-Za-z%]*\b", clean_text))
    sentence_word_count = len(re.findall(r"\b[a-z]{4,}\b", clean_text))
    symbol_ratio = (digit_count + operator_count) / max(len(compact_text), 1)

    if symbol_ratio >= 0.45 and letter_count <= digit_count + operator_count:
        return True
    if numeric_token_count >= 8 and sentence_word_count <= max(word_count * 0.35, 3):
        return True
    return False


def _block_is_expected_to_translate(block: Dict[str, Any]) -> bool:
    if block.get("type") != "text":
        return False
    if block.get("is_header_footer_metadata") or block.get("is_formula") or block.get("is_chart_text"):
        return False
    if block.get("layout_role") in {"metadata", "dense_reference", "vertical_text"}:
        return False
    source_text = str(block.get("text") or "").strip()
    if not source_text:
        return False
    return not _looks_numeric_or_formula_like(source_text)


def _scan_block(block: Dict[str, Any]) -> List[Dict[str, Any]]:
    warnings: List[Dict[str, Any]] = []
    source_text = str(block.get("text") or "")
    translated_text = str(block.get("translatedText") or "")
    source_compact = _normalize_token(source_text)
    translated_compact = _normalize_token(translated_text)

    if _block_is_expected_to_translate(block) and not translated_text.strip():
        warnings.append({
            "code": "missing_translation",
            "severity": "warning",
            "message": "Text block has no translated text.",
        })
        return warnings

    if not translated_text.strip():
        return warnings

    suspicious_glyphs = _count_suspicious_glyphs(translated_text)
    if suspicious_glyphs:
        warnings.append({
            "code": "suspicious_glyphs",
            "severity": "warning",
            "count": suspicious_glyphs,
            "message": "Translated text contains replacement/tofu/question-mark glyph patterns.",
        })

    marker = _leading_layout_marker(source_text)
    if marker and not translated_text.lstrip().startswith(marker):
        warnings.append({
            "code": "missing_marker",
            "severity": "warning",
            "marker": marker,
            "message": "Translated text does not preserve the source leading marker.",
        })

    source_tokens = _extract_numeric_symbols(source_text)
    if source_tokens:
        missing_tokens = [
            token for token in source_tokens
            if token not in translated_compact
        ]
        if missing_tokens:
            warnings.append({
                "code": "missing_numeric_symbol",
                "severity": "warning",
                "tokens": missing_tokens[:8],
                "message": "Translated text may have lost numeric symbols, percentages, ranges, or comparison operators.",
            })

    if "\n" in translated_text.strip():
        warnings.append({
            "code": "unexpected_line_break",
            "severity": "info",
            "message": "Translated text contains explicit line breaks inside a block.",
        })

    if (
        len(source_compact) >= 30
        and len(translated_compact) > len(source_compact) * 4.0
        and not source_text.rstrip().endswith(SENTENCE_ENDINGS)
    ):
        warnings.append({
            "code": "length_ratio_high",
            "severity": "info",
            "ratio": round(len(translated_compact) / max(len(source_compact), 1), 2),
            "message": "Translated text is much longer than the source block.",
        })

    return warnings


def build_pdf_quality_report(
    translation_result: Dict[str, Any],
    *,
    output_type: Optional[str] = None,
    source_bytes: Optional[int] = None,
    export_bytes: Optional[int] = None,
    size_warn_ratio: float = 2.2,
) -> Dict[str, Any]:
    pages = []
    total_warnings = 0
    warning_counts: Dict[str, int] = {}

    for page_data in translation_result.get("pages", []):
        page_warnings: List[Dict[str, Any]] = []
        translated_blocks = 0
        expected_blocks = 0
        suspicious_glyphs = 0

        for block_index, block in enumerate(page_data.get("textBlocks", [])):
            if _block_is_expected_to_translate(block):
                expected_blocks += 1
            if str(block.get("translatedText") or "").strip():
                translated_blocks += 1

            block_warnings = _scan_block(block)
            for warning in block_warnings:
                warning = dict(warning)
                warning["blockIndex"] = block_index
                page_warnings.append(warning)
                warning_counts[warning["code"]] = warning_counts.get(warning["code"], 0) + 1
                if warning["code"] == "suspicious_glyphs":
                    suspicious_glyphs += int(warning.get("count") or 0)

        if expected_blocks and translated_blocks == 0:
            warning = {
                "code": "blank_translated_page",
                "severity": "warning",
                "message": "Page has expected translatable blocks but no translated text.",
            }
            page_warnings.append(warning)
            warning_counts[warning["code"]] = warning_counts.get(warning["code"], 0) + 1

        total_warnings += len(page_warnings)
        pages.append({
            "page": page_data.get("pageNum"),
            "status": "warn" if page_warnings else "ok",
            "blocks": len(page_data.get("textBlocks", [])),
            "expectedTranslatedBlocks": expected_blocks,
            "translatedBlocks": translated_blocks,
            "suspiciousGlyphs": suspicious_glyphs,
            "warnings": page_warnings,
        })

    size_ratio = None
    size_warning = False
    if source_bytes and export_bytes:
        size_ratio = round(export_bytes / max(source_bytes, 1), 3)
        size_warning = size_ratio > size_warn_ratio
        if size_warning:
            warning_counts["export_size_ratio_high"] = warning_counts.get("export_size_ratio_high", 0) + 1
            total_warnings += 1

    return {
        "status": "warn" if total_warnings else "ok",
        "outputType": output_type,
        "pages": pages,
        "summary": {
            "pages": len(pages),
            "warnings": total_warnings,
            "warningCounts": warning_counts,
            "sourceBytes": source_bytes,
            "exportBytes": export_bytes,
            "sizeRatio": size_ratio,
            "sizeWarnRatio": size_warn_ratio if source_bytes and export_bytes else None,
            "sizeWarning": size_warning,
        },
    }
