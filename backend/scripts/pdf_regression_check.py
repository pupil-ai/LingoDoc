import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api import routes  # noqa: E402
from app.services.pdf_quality_service import build_pdf_quality_report  # noqa: E402
from app.services.pdf_service import PDFService  # noqa: E402
from app.services.storage_service import storage_service  # noqa: E402
from app.services.translate_service import TranslationServiceFactory  # noqa: E402


class StructureEchoTranslator:
    async def translate_structured_batch(
        self,
        items: List[Dict[str, Any]],
        source_lang: str,
        target_lang: str,
    ) -> List[str]:
        return [str(item.get("text") or "") for item in items]


def _parse_pages(raw_pages: str) -> List[int]:
    pages: List[int] = []
    for part in raw_pages.split(","):
        part = part.strip()
        if not part:
            continue
        page = int(part)
        if page < 1:
            raise ValueError("Pages must be 1-based positive integers")
        pages.append(page)
    return pages


def _page_text(page_content: Dict[str, Any]) -> str:
    return "\n".join(
        str(block.get("text") or "")
        for block in page_content.get("textBlocks", [])
    )


async def _translate_pages(
    service: PDFService,
    translator: Any,
    file_id: str,
    pages: List[int],
    source_lang: str,
    target_lang: str,
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for page_number in pages:
        page_started = time.perf_counter()
        page_index = page_number - 1
        content = service.extract_page_content(file_id, page_index)
        translated_blocks = await routes._translate_page_blocks(
            translator,
            content["textBlocks"],
            source_lang,
            target_lang,
            page_number=page_number,
        )
        result = routes._build_page_result(page_index, _page_text(content), translated_blocks)
        result["regressionElapsedMs"] = int((time.perf_counter() - page_started) * 1000)
        results.append(result)
    return results


def _build_summary(
    *,
    pdf_path: Path,
    pages: List[int],
    translator_name: str,
    elapsed_ms: int,
    result: Dict[str, Any],
    quality_report: Dict[str, Any],
    export_bytes: int,
    output_dir: Path,
) -> Dict[str, Any]:
    translated_blocks = 0
    total_blocks = 0
    for page in result.get("pages", []):
        blocks = page.get("textBlocks", [])
        total_blocks += len(blocks)
        translated_blocks += len([
            block for block in blocks
            if str(block.get("translatedText") or "").strip()
        ])

    return {
        "pdf": str(pdf_path),
        "pages": pages,
        "translator": translator_name,
        "elapsedMs": elapsed_ms,
        "totalBlocks": total_blocks,
        "translatedBlocks": translated_blocks,
        "qualityStatus": quality_report.get("status"),
        "qualitySummary": quality_report.get("summary"),
        "exportBytes": export_bytes,
        "outputDir": str(output_dir.resolve()),
    }


def _parse_page_value(raw_value: str, *, value_type: str) -> tuple[int, Any]:
    if ":" not in raw_value:
        raise ValueError(f"Expected PAGE:{value_type}, got {raw_value!r}")
    page_raw, value = raw_value.split(":", 1)
    page = int(page_raw.strip())
    if page < 1:
        raise ValueError("Pages must be 1-based positive integers")
    return page, value


def _page_result_by_number(result: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    return {
        int(page.get("pageNum")): page
        for page in result.get("pages", [])
        if page.get("pageNum")
    }


def _page_combined_text(page: Dict[str, Any]) -> str:
    parts: List[str] = []
    for block in page.get("textBlocks", []):
        parts.append(str(block.get("text") or ""))
        parts.append(str(block.get("translatedText") or ""))
    return "\n".join(part for part in parts if part)


def _translated_block_count(page: Dict[str, Any]) -> int:
    return len([
        block for block in page.get("textBlocks", [])
        if str(block.get("translatedText") or "").strip()
    ])


def _run_assertions(
    result: Dict[str, Any],
    quality_report: Dict[str, Any],
    args: argparse.Namespace,
) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    pages = _page_result_by_number(result)

    for raw in args.require_token:
        page_number, token = _parse_page_value(raw, value_type="TOKEN")
        page = pages.get(page_number)
        if not page:
            failures.append({"code": "missing_page", "page": page_number, "expected": token})
            continue
        if str(token) not in _page_combined_text(page):
            failures.append({"code": "missing_required_token", "page": page_number, "token": token})

    for raw in args.min_skip_ratio:
        page_number, ratio_raw = _parse_page_value(raw, value_type="RATIO")
        expected_ratio = float(ratio_raw)
        page = pages.get(page_number)
        if not page:
            failures.append({"code": "missing_page", "page": page_number, "expected": expected_ratio})
            continue
        total_blocks = len(page.get("textBlocks", []))
        translated_blocks = _translated_block_count(page)
        skip_ratio = (total_blocks - translated_blocks) / max(total_blocks, 1)
        if skip_ratio < expected_ratio:
            failures.append({
                "code": "skip_ratio_low",
                "page": page_number,
                "expected": expected_ratio,
                "actual": round(skip_ratio, 3),
                "totalBlocks": total_blocks,
                "translatedBlocks": translated_blocks,
            })

    if args.max_size_ratio is not None:
        size_ratio = (quality_report.get("summary") or {}).get("sizeRatio")
        if size_ratio is not None and float(size_ratio) > args.max_size_ratio:
            failures.append({
                "code": "size_ratio_high",
                "expected": args.max_size_ratio,
                "actual": size_ratio,
            })

    return failures


async def run_regression(args: argparse.Namespace) -> int:
    load_dotenv(ROOT / ".env")
    pdf_path = Path(args.pdf).expanduser().resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    pages = _parse_pages(args.pages)
    output_dir = Path(args.output_dir).resolve() if args.output_dir else ROOT / "outputs" / "pdf_regression"
    output_dir.mkdir(parents=True, exist_ok=True)

    service = PDFService()
    translator = (
        StructureEchoTranslator()
        if args.translator == "echo"
        else TranslationServiceFactory.get(args.translator)
    )

    file_id = service.save_uploaded_file(pdf_path.read_bytes())
    started = time.perf_counter()
    try:
        page_results = await _translate_pages(
            service,
            translator,
            file_id,
            pages,
            args.source_lang,
            args.target_lang,
        )
        result = {"pages": page_results}
        result_path = output_dir / "translation_result.json"
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

        pdf_bytes = service.generate_bilingual_pdf(file_id, result)
        pdf_output_path = output_dir / "bilingual.pdf"
        pdf_output_path.write_bytes(pdf_bytes)

        for export_page_index, page_number in enumerate(pages):
            preview_bytes = service.generate_pdf_file_page_preview_png(
                str(pdf_output_path),
                page_num=export_page_index,
                max_width=args.preview_width,
            )
            (output_dir / f"page_{page_number}.png").write_bytes(preview_bytes)

        quality_report = build_pdf_quality_report(
            result,
            output_type="bilingual",
            source_bytes=pdf_path.stat().st_size,
            export_bytes=len(pdf_bytes),
        )
        assertion_failures = _run_assertions(result, quality_report, args)
        quality_path = output_dir / "bilingual.quality.json"
        quality_path.write_text(json.dumps(quality_report, ensure_ascii=False, indent=2), encoding="utf-8")

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        summary = _build_summary(
            pdf_path=pdf_path,
            pages=pages,
            translator_name=args.translator,
            elapsed_ms=elapsed_ms,
            result=result,
            quality_report=quality_report,
            export_bytes=len(pdf_bytes),
            output_dir=output_dir,
        )
        summary["assertions"] = {
            "status": "failed" if assertion_failures else "ok",
            "failures": assertion_failures,
        }
        (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))

        warning_count = int((quality_report.get("summary") or {}).get("warnings") or 0)
        return 1 if warning_count > args.max_warnings or assertion_failures else 0
    finally:
        storage_service.delete(service.get_file_storage_key(file_id))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a PDF translation/export quality regression check.")
    parser.add_argument("--pdf", required=True, help="Source PDF path.")
    parser.add_argument("--pages", default="2,8,9", help="1-based comma-separated pages to test.")
    parser.add_argument("--translator", default="echo", help="Translator name: echo, mock, ofoxai, openai, deepl, google.")
    parser.add_argument("--source-lang", default="en")
    parser.add_argument("--target-lang", default="zh")
    parser.add_argument("--preview-width", type=int, default=1800)
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--max-warnings", type=int, default=0)
    parser.add_argument(
        "--require-token",
        action="append",
        default=[],
        help="Require PAGE:TOKEN to appear in source or translated text. May be repeated.",
    )
    parser.add_argument(
        "--min-skip-ratio",
        action="append",
        default=[],
        help="Require PAGE:RATIO skipped blocks ratio. May be repeated.",
    )
    parser.add_argument("--max-size-ratio", type=float, default=None)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return asyncio.run(run_regression(args))


if __name__ == "__main__":
    raise SystemExit(main())
