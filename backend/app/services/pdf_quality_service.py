import re
import unicodedata
from typing import Any, Dict, List, Optional, Set, Tuple

from app.services.translation_text_utils import count_suspicious_translation_glyphs

SENTENCE_ENDINGS = (".", "!", "?", ";", ":", "\u3002", "\uff01", "\uff1f", "\uff1b", "\uff1a")


def _normalize_token(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _normalize_numeric_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "")
    normalized = normalized.replace("\u2264", "<=").replace("\u2265", ">=")
    normalized = normalized.replace("\u2212", "-")
    normalized = re.sub(r"[\u2010-\u2015]", "-", normalized)
    return normalized


def _normalize_numeric_token(text: str) -> str:
    token = _normalize_token(_normalize_numeric_text(text))
    token = re.sub(r"(?<=\d),(?=\d)", ".", token)
    return token


def _normalize_number_value(value: str) -> str:
    value = _normalize_numeric_text(value)
    value = re.sub(r"(?<=\d)[\s\u00a0\u202f](?=\d)", "", value)
    value = re.sub(r"[^\d.,]", "", value)
    if not value:
        return ""

    separators = re.findall(r"[.,]", value)
    if not separators:
        return value

    parts = re.split(r"[.,]", value)
    if len(separators) > 1:
        if all(len(part) == 3 for part in parts[1:]):
            return "".join(parts)
        integer_part = "".join(parts[:-1])
        return f"{integer_part}.{parts[-1]}"

    before, after = parts[0], parts[1]
    if len(after) == 3 and before and before != "0":
        return before + after
    return f"{before}.{after}"


def _numeric_match_keys(text: str) -> Set[str]:
    normalized = _normalize_numeric_text(text)
    keys = {_normalize_numeric_token(normalized)}
    number = r"\d+(?:[\s\u00a0\u202f]?\d{3})*(?:[.,]\d+)?|\d+(?:[.,]\d+)*"
    patterns = [
        rf"(?P<cmp><=|>=|[<>])?\s*(?P<num>{number})\s*(?P<pct>%)?",
        rf"(?P<cmp><=|>=|[<>])?\s*%\s*(?P<num>{number})",
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, normalized):
            value = _normalize_number_value(match.group("num"))
            if not value:
                continue
            comparator = match.groupdict().get("cmp") or ""
            has_percent = bool(match.groupdict().get("pct")) or "%" in match.group(0)

            keys.add(value)
            if has_percent:
                keys.add(f"{value}%")
                keys.add(f"%{value}")

            if comparator:
                keys.add(f"{comparator}{value}")
                if has_percent:
                    keys.add(f"{comparator}{value}%")
                    keys.add(f"{comparator}%{value}")
                    # Comparators are commonly translated as words, while the
                    # numeric percentage still needs to be preserved.
                    keys.add(f"{value}%")

    return {key for key in keys if key}


def _range_endpoint_keys(token: str) -> Optional[Tuple[Set[str], Set[str]]]:
    normalized = _normalize_numeric_text(token)
    if "-" not in normalized:
        return None

    parts = [part for part in normalized.split("-") if part.strip()]
    if len(parts) != 2:
        return None

    return _numeric_match_keys(parts[0]), _numeric_match_keys(parts[1])


def _translated_contains_numeric_token(token: str, translated_keys: Set[str]) -> bool:
    endpoint_keys = _range_endpoint_keys(token)
    if endpoint_keys:
        left_keys, right_keys = endpoint_keys
        return bool(left_keys & translated_keys) and bool(right_keys & translated_keys)

    source_keys = _numeric_match_keys(token)
    return bool(source_keys & translated_keys)


def _leading_layout_marker(text: str) -> str:
    stripped = (text or "").lstrip()
    marker_match = re.match(
        r"^((?:[\*\u2022\u00b7\-–—]\s+)|(?:\(?[A-Za-z0-9ivxlcdmIVXLCDM]{1,8}[\).]\s+))",
        stripped,
    )
    return marker_match.group(1) if marker_match else ""


def _extract_numeric_symbols(text: str) -> List[str]:
    normalized = _normalize_numeric_text(text)
    patterns = [
        r"(?:<=|>=|[<>])\s*\d+(?:[\s\u00a0\u202f]?\d{3})*(?:[.,]\d+)?\s*%?",
        r"\d+(?:[.,]\d+)?\s*%",
        r"%\s*\d+(?:[.,]\d+)?",
        r"\d+(?:[.,]\d+)?\s*-\s*\d+(?:[.,]\d+)?\s*%?",
    ]
    tokens: List[str] = []
    for pattern in patterns:
        for match in re.findall(pattern, normalized):
            token = _normalize_token(match)
            if token and token not in tokens:
                tokens.append(token)
    return tokens[:24]


def _count_suspicious_glyphs(text: str) -> int:
    suspicious = count_suspicious_translation_glyphs(text)
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
    translated_numeric_keys = _numeric_match_keys(translated_text)

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
            if not _translated_contains_numeric_token(token, translated_numeric_keys)
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
