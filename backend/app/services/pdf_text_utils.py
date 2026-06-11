import re
import unicodedata


SENTENCE_ENDINGS = (
    ".",
    "!",
    "?",
    ";",
    ":",
    "\u3002",
    "\uff01",
    "\uff1f",
    "\uff1b",
    "\uff1a",
)
HEADING_PUNCTUATION = set(".\u3002!?\uff01\uff1f:\uff1a;\uff1b")
CJK_PUNCTUATION = set("\uff0c\u3002\uff01\uff1f\uff1b\uff1a\uff08\uff09\u300a\u300b\u201c\u201d\u2018\u2019\u3001")
MARKER_GLYPHS = {"\u2022", "\u00b7", "\u25cf", "\u25c6", "\u25a0", "-", "/", "\\", "|"}
MATH_SYMBOLS = set("=<>+/-*^_{}[]|\u00b1\u00d7\u00f7\u2248\u2260\u2264\u2265\u221a\u2211\u222b\u221e\u2202\u2206\u2207\u2192\u2190\u2194")


def normalize_pdf_text(text: str, preserve_leading_space: bool = False) -> str:
    normalized = text or ""
    normalized = normalized.replace("\u00a0", " ")
    normalized = normalized.replace("\u200b", "")
    normalized = normalized.replace("\ufeff", "")
    normalized = re.sub(r"\s+", " ", normalized)
    if preserve_leading_space:
        return normalized.rstrip()
    return normalized.strip()


def has_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def has_emoji(text: str) -> bool:
    return any(ord(char) > 0xFFFF for char in text)


def is_symbol_emoji(char: str) -> bool:
    if not char:
        return False
    if ord(char) > 0xFFFF:
        return True
    return unicodedata.category(char) == "So" and char not in MARKER_GLYPHS
