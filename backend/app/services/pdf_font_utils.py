import os
from pathlib import Path
from typing import Any


SCRIPT_LATIN = "latin"
SCRIPT_LATIN_EXTENDED = "latin_extended"
SCRIPT_CYRILLIC = "cyrillic"
SCRIPT_GREEK = "greek"
SCRIPT_CJK = "cjk"
SCRIPT_OTHER = "other"


TRANSLATION_FONT_REGULAR_ENV = "PDF_TRANSLATION_FONT_REGULAR"
TRANSLATION_FONT_BOLD_ENV = "PDF_TRANSLATION_FONT_BOLD"
TRANSLATION_LATIN_FONT_REGULAR_ENV = "PDF_TRANSLATION_LATIN_FONT_REGULAR"
TRANSLATION_LATIN_FONT_BOLD_ENV = "PDF_TRANSLATION_LATIN_FONT_BOLD"
BACKEND_ROOT = Path(__file__).resolve().parents[2]


class TranslationFontConfigurationError(RuntimeError):
    pass


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
        elif codepoint <= 0x00FF:
            scripts.add(SCRIPT_LATIN)
        elif codepoint <= 0x024F or 0x1E00 <= codepoint <= 0x1EFF:
            scripts.add(SCRIPT_LATIN_EXTENDED)
        else:
            scripts.add(SCRIPT_OTHER)
    return scripts


def detect_page_required_scripts(page_data: dict[str, Any]) -> set[str]:
    scripts: set[str] = set()
    for block in page_data.get("textBlocks", []):
        scripts.update(detect_required_scripts(str(block.get("translatedText") or "")))
    return scripts


def _resolve_configured_font_path(env_name: str) -> str:
    raw_path = os.getenv(env_name, "").strip()
    if not raw_path:
        raise TranslationFontConfigurationError(
            f"{env_name} is required. Use the same Docker image locally and in production, "
            "and point this variable at the bundled translation font."
        )

    font_path = Path(raw_path).expanduser()
    if not font_path.is_absolute():
        font_path = BACKEND_ROOT / font_path
    font_path = font_path.resolve()

    if not font_path.exists():
        raise TranslationFontConfigurationError(f"{env_name} does not exist: {font_path}")
    if not font_path.is_file():
        raise TranslationFontConfigurationError(f"{env_name} is not a file: {font_path}")
    return str(font_path)


def get_translation_font_paths() -> tuple[str, str]:
    regular_font_path = _resolve_configured_font_path(TRANSLATION_FONT_REGULAR_ENV)
    bold_font_path = _resolve_configured_font_path(TRANSLATION_FONT_BOLD_ENV)
    return regular_font_path, bold_font_path


def get_latin_translation_font_paths() -> tuple[str, str]:
    regular_font_path = _resolve_configured_font_path(TRANSLATION_LATIN_FONT_REGULAR_ENV)
    bold_font_path = _resolve_configured_font_path(TRANSLATION_LATIN_FONT_BOLD_ENV)
    return regular_font_path, bold_font_path


def _validate_font_pair(label: str, regular_font_path: str, bold_font_path: str) -> None:
    try:
        import fitz

        doc = fitz.open()
        try:
            page = doc.new_page()
            safe_label = "".join(char if char.isalnum() else "_" for char in label)
            page.insert_font(fontfile=regular_font_path, fontname=f"{safe_label}_regular_validation")
            page.insert_font(fontfile=bold_font_path, fontname=f"{safe_label}_bold_validation")
        finally:
            doc.close()
    except Exception as exc:
        raise TranslationFontConfigurationError(
            f"Configured PDF translation fonts for {label} could not be registered by PyMuPDF: "
            f"{regular_font_path}, {bold_font_path}. Error: {exc}"
        ) from exc


def validate_translation_fonts() -> tuple[str, str]:
    regular_font_path, bold_font_path = get_translation_font_paths()
    _validate_font_pair("default", regular_font_path, bold_font_path)

    latin_regular_font_path, latin_bold_font_path = get_latin_translation_font_paths()
    _validate_font_pair("latin", latin_regular_font_path, latin_bold_font_path)

    print(
        "[STARTUP] PDF translation fonts ready: "
        f"regular={regular_font_path} bold={bold_font_path} "
        f"latin_regular={latin_regular_font_path} "
        f"latin_bold={latin_bold_font_path}"
    )
    return regular_font_path, bold_font_path


def resolve_translation_font_paths(required_scripts: set[str]) -> tuple[str, str]:
    if not required_scripts or required_scripts <= {SCRIPT_LATIN}:
        return "", ""

    if required_scripts & {SCRIPT_LATIN_EXTENDED, SCRIPT_CYRILLIC, SCRIPT_GREEK}:
        return get_latin_translation_font_paths()

    return get_translation_font_paths()
