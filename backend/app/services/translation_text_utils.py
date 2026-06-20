import re
import unicodedata


PRESERVED_SYMBOL_GLYPHS = {"\u2022", "\u00b7", "\u25cf", "\u25c6", "\u25a0", "-", "/", "\\", "|"}
TOFU_GLYPHS = {
    "\ufffd",
    "\u25a1",
    "\u25a2",
    "\u25af",
    "\u25cc",
    "\u25fb",
    "\u25fc",
    "\u2610",
    "\u2751",
    "\u2752",
}

PUNCTUATION_TRANSLATION = str.maketrans({
    "\u00ad": "",
    "\u2010": "-",
    "\u2011": "-",
    "\u2012": "-",
    "\u2013": "-",
    "\u2014": "-",
    "\u2015": "-",
    "\u2212": "-",
    "\u2018": "'",
    "\u2019": "'",
    "\u201a": "'",
    "\u201b": "'",
    "\u2032": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u201e": '"',
    "\u201f": '"',
    "\u2033": '"',
    "\u2026": "...",
    "\u00a0": " ",
    "\u202f": " ",
    "\u2007": " ",
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\ufb05": "st",
    "\ufb06": "st",
})


def _is_private_use_or_surrogate(char: str) -> bool:
    codepoint = ord(char)
    return (
        0xD800 <= codepoint <= 0xDFFF
        or 0xE000 <= codepoint <= 0xF8FF
        or 0xF0000 <= codepoint <= 0xFFFFD
        or 0x100000 <= codepoint <= 0x10FFFD
    )


def _is_emoji_or_unstable_symbol(char: str) -> bool:
    codepoint = ord(char)
    if codepoint > 0xFFFF:
        return True
    if 0x2600 <= codepoint <= 0x27BF:
        return char not in PRESERVED_SYMBOL_GLYPHS
    return unicodedata.category(char) == "So" and char not in PRESERVED_SYMBOL_GLYPHS


def count_suspicious_translation_glyphs(text: str) -> int:
    count = 0
    for char in text or "":
        if char in TOFU_GLYPHS or _is_private_use_or_surrogate(char) or _is_emoji_or_unstable_symbol(char):
            count += 1
            continue
        category = unicodedata.category(char)
        if category == "Cc" and char not in "\r\n\t":
            count += 1
    return count


def sanitize_translated_text(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text or "")
    normalized = normalized.translate(PUNCTUATION_TRANSLATION)

    cleaned_chars: list[str] = []
    for char in normalized:
        if char in TOFU_GLYPHS or _is_private_use_or_surrogate(char) or _is_emoji_or_unstable_symbol(char):
            continue

        category = unicodedata.category(char)
        if category == "Cc":
            cleaned_chars.append(" " if char in "\r\n\t" else "")
            continue
        if category == "Cf":
            continue

        cleaned_chars.append(char)

    cleaned = "".join(cleaned_chars)
    cleaned = re.sub(r"[ \t]*[\r\n]+[ \t]*", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()
