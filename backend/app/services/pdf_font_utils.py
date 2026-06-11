import os
from typing import Any, Iterable


SCRIPT_LATIN = "latin"
SCRIPT_CYRILLIC = "cyrillic"
SCRIPT_GREEK = "greek"
SCRIPT_CJK = "cjk"
SCRIPT_OTHER = "other"


def find_existing_font(font_paths: Iterable[str]) -> str:
    for font_path in font_paths:
        if font_path and os.path.exists(font_path):
            return font_path
    return ""


def detect_required_scripts(text: str) -> set[str]:
    scripts: set[str] = set()
    for char in text or "":
        codepoint = ord(char)
        if char.isspace() or char.isdigit() or char in ".,;:!?()[]{}<>\"'`~@#$%^&*-_=+\\/|":
            continue
        if (
            0x4E00 <= codepoint <= 0x9FFF
            or 0x3040 <= codepoint <= 0x30FF
            or 0xAC00 <= codepoint <= 0xD7AF
            or 0x3400 <= codepoint <= 0x4DBF
        ):
            scripts.add(SCRIPT_CJK)
        elif 0x0400 <= codepoint <= 0x052F:
            scripts.add(SCRIPT_CYRILLIC)
        elif 0x0370 <= codepoint <= 0x03FF:
            scripts.add(SCRIPT_GREEK)
        elif codepoint <= 0x024F or 0x1E00 <= codepoint <= 0x1EFF:
            scripts.add(SCRIPT_LATIN)
        else:
            scripts.add(SCRIPT_OTHER)
    return scripts


def detect_page_required_scripts(page_data: dict[str, Any]) -> set[str]:
    scripts: set[str] = set()
    for block in page_data.get("textBlocks", []):
        scripts.update(detect_required_scripts(str(block.get("translatedText") or "")))
    return scripts


def resolve_translation_font_paths(required_scripts: set[str]) -> tuple[str, str]:
    if not required_scripts or required_scripts <= {SCRIPT_LATIN}:
        return "", ""

    if SCRIPT_CJK in required_scripts or SCRIPT_OTHER in required_scripts:
        cjk_font_paths = [
            "C:\\Windows\\Fonts\\msyh.ttc",
            "C:\\Windows\\Fonts\\simhei.ttf",
            "C:\\Windows\\Fonts\\Dengl.ttf",
            "C:\\Windows\\Fonts\\Deng.ttf",
            "C:\\Windows\\Fonts\\NotoSansSC-VF.ttf",
            "C:\\Windows\\Fonts\\simsun.ttc",
            "C:\\Windows\\Fonts\\msgothic.ttc",
            "C:\\Windows\\Fonts\\YuGothR.ttc",
        ]
        regular_font_path = find_existing_font(cjk_font_paths)
        bold_candidates = [
            "C:\\Windows\\Fonts\\msyhbd.ttc",
            "C:\\Windows\\Fonts\\simhei.ttf",
            "C:\\Windows\\Fonts\\Dengb.ttf",
            regular_font_path,
            "C:\\Windows\\Fonts\\simsunb.ttf",
        ]
        bold_font_path = find_existing_font(bold_candidates) or regular_font_path
        return regular_font_path, bold_font_path

    regular_font_path = find_existing_font([
        "C:\\Windows\\Fonts\\arial.ttf",
        "C:\\Windows\\Fonts\\segoeui.ttf",
        "C:\\Windows\\Fonts\\tahoma.ttf",
        "C:\\Windows\\Fonts\\calibri.ttf",
        "C:\\Windows\\Fonts\\times.ttf",
    ])
    bold_font_path = find_existing_font([
        "C:\\Windows\\Fonts\\arialbd.ttf",
        "C:\\Windows\\Fonts\\segoeuib.ttf",
        "C:\\Windows\\Fonts\\tahomabd.ttf",
        "C:\\Windows\\Fonts\\calibrib.ttf",
        regular_font_path,
    ])
    return regular_font_path, bold_font_path
