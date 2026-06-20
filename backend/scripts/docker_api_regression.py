import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import aiohttp
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.auth import CurrentUser
from app.api import routes as api_routes
from app.services.pdf_quality_service import build_pdf_quality_report
from app.services.translate_service import SUPPORTED_LANGUAGE_CODES


TEST_HOST = "127.0.0.1"
TEST_PORT = 8765
BASE_URL = f"http://{TEST_HOST}:{TEST_PORT}"


def _json_default(value: Any) -> str:
    return str(value)


async def _fake_current_user() -> CurrentUser:
    return CurrentUser(
        id=os.getenv("CODEX_REGRESSION_USER_ID", "codex-docker-regression"),
        claims={"sub": os.getenv("CODEX_REGRESSION_USER_ID", "codex-docker-regression")},
    )


async def _fake_optional_current_user() -> CurrentUser:
    return await _fake_current_user()


async def _start_server() -> uvicorn.Server:
    api_routes.router.dependency_overrides_provider = None
    api_routes.db_service.upsert_user((await _fake_current_user()).id, "codex-regression@example.test")
    api_routes.db_service.update_user_subscription(
        user_id=(await _fake_current_user()).id,
        plan=os.getenv("CODEX_REGRESSION_PLAN", "free"),
        subscription_status=os.getenv("CODEX_REGRESSION_SUBSCRIPTION_STATUS", "inactive"),
    )

    from main import app

    app.dependency_overrides[api_routes.get_current_user] = _fake_current_user
    app.dependency_overrides[api_routes.get_optional_current_user] = _fake_optional_current_user

    config = uvicorn.Config(app, host=TEST_HOST, port=TEST_PORT, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    server._codex_task = task  # type: ignore[attr-defined]

    timeout_at = time.monotonic() + 30
    async with aiohttp.ClientSession() as session:
        while time.monotonic() < timeout_at:
            try:
                async with session.get(f"{BASE_URL}/") as response:
                    if response.status == 200:
                        return server
            except Exception:
                pass
            await asyncio.sleep(0.25)
    raise RuntimeError("Timed out waiting for API server")


async def _stop_server(server: uvicorn.Server) -> None:
    server.should_exit = True
    task = getattr(server, "_codex_task", None)
    if task is not None:
        await task


async def _request_json(session: aiohttp.ClientSession, method: str, path: str, **kwargs) -> dict[str, Any]:
    async with session.request(method, f"{BASE_URL}{path}", **kwargs) as response:
        text = await response.text()
        if response.status >= 400:
            raise RuntimeError(f"{method} {path} failed: {response.status} {text[:500]}")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{method} {path} returned non-JSON: {text[:500]}") from exc


async def _request_bytes(session: aiohttp.ClientSession, method: str, path: str, **kwargs) -> bytes:
    async with session.request(method, f"{BASE_URL}{path}", **kwargs) as response:
        body = await response.read()
        if response.status >= 400:
            raise RuntimeError(f"{method} {path} failed: {response.status} {body[:500]!r}")
        return body


async def _upload_pdf(session: aiohttp.ClientSession, pdf_path: Path) -> dict[str, Any]:
    data = aiohttp.FormData()
    with pdf_path.open("rb") as handle:
        data.add_field(
            "file",
            handle,
            filename=pdf_path.name,
            content_type="application/pdf",
        )
        return await _request_json(session, "POST", "/api/upload", data=data)


async def _wait_for_translation(session: aiohttp.ClientSession, task_id: str, timeout_seconds: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_progress: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last_progress = await _request_json(session, "GET", f"/api/translate/{task_id}/progress")
        status = str(last_progress.get("status") or "")
        if status == "completed":
            return last_progress
        if status in {"error", "failed"}:
            raise RuntimeError(f"Translation {task_id} failed: {last_progress}")
        await asyncio.sleep(2)
    raise TimeoutError(f"Timed out waiting for translation {task_id}: {last_progress}")


async def _wait_for_export(
    session: aiohttp.ClientSession,
    task_id: str,
    output_type: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_status: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last_status = await _request_json(session, "GET", f"/api/export/{task_id}/jobs/{output_type}")
        status = str(last_status.get("status") or "")
        if status == "ready":
            return last_status
        if status == "error":
            raise RuntimeError(f"Export {task_id}/{output_type} failed: {last_status}")
        await asyncio.sleep(2)
    raise TimeoutError(f"Timed out waiting for export {task_id}/{output_type}: {last_status}")


def _count_text_blocks_with_emoji(result: dict[str, Any]) -> int:
    total = 0
    for page in result.get("pages", []):
        for block in page.get("textBlocks", []):
            text = str(block.get("text") or "")
            if any(ord(char) > 0xFFFF for char in text):
                total += 1
    return total


async def _run_case(
    session: aiohttp.ClientSession,
    pdf_path: Path,
    target_lang: str,
    *,
    source_lang: str,
    preview_dir: Path,
    save_preview: bool,
    render_exports: bool,
    timeout_seconds: int,
) -> dict[str, Any]:
    upload = await _upload_pdf(session, pdf_path)
    file_id = upload["fileId"]
    started = await _request_json(
        session,
        "POST",
        "/api/translate",
        json={"fileId": file_id, "sourceLang": source_lang, "targetLang": target_lang},
    )
    task_id = started["taskId"]
    progress = await _wait_for_translation(session, task_id, timeout_seconds)
    result = await _request_json(session, "GET", f"/api/translate/{task_id}/result?include_pages=true")
    quality = build_pdf_quality_report(result, output_type="bilingual")

    preview_bytes = await _request_bytes(
        session,
        "GET",
        f"/api/translate/{task_id}/pages/1/preview?width=1400",
    )
    preview_path = None
    if save_preview:
        preview_dir.mkdir(parents=True, exist_ok=True)
        preview_path = preview_dir / f"{pdf_path.stem}_{target_lang}_page1.png"
        preview_path.write_bytes(preview_bytes)

    export_summary: dict[str, Any] = {}
    if render_exports:
        for output_type in ("bilingual", "translated"):
            await _request_json(
                session,
                "POST",
                f"/api/export/{task_id}/jobs",
                json={"outputType": output_type},
            )
            export_status = await _wait_for_export(session, task_id, output_type, timeout_seconds)
            export_bytes = await _request_bytes(
                session,
                "GET",
                f"/api/export/{task_id}?format=pdf&output_type={output_type}&download=true",
            )
            export_summary[output_type] = {
                "status": export_status.get("status"),
                "bytes": len(export_bytes),
                "sizeWarning": export_status.get("sizeWarning"),
            }

    summary = quality.get("summary") or {}
    return {
        "file": pdf_path.name,
        "target": target_lang,
        "taskId": task_id,
        "requestedPages": started.get("requestedPages"),
        "translatedPages": progress.get("translatedPages"),
        "previewBytes": len(preview_bytes),
        "previewPath": str(preview_path) if preview_path else None,
        "emojiTextBlocks": _count_text_blocks_with_emoji(result),
        "qualityStatus": quality.get("status"),
        "qualityWarnings": summary.get("warnings", 0),
        "qualityWarningCounts": summary.get("warningCounts", {}),
        "exports": export_summary,
    }


async def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", nargs="+", required=True)
    parser.add_argument("--source", default="en")
    parser.add_argument("--targets", nargs="*", default=None)
    parser.add_argument("--export-targets", nargs="*", default=["it", "zh", "ja"])
    parser.add_argument("--preview-dir", default="/app/tmp/codex-api-regression-previews")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    args = parser.parse_args()

    pdf_paths = [Path(path) for path in args.inputs]
    for pdf_path in pdf_paths:
        if not pdf_path.exists():
            raise FileNotFoundError(pdf_path)

    targets = args.targets or [lang for lang in SUPPORTED_LANGUAGE_CODES if lang != args.source]
    preview_dir = Path(args.preview_dir)
    server = await _start_server()
    started_at = time.monotonic()
    failures: list[dict[str, Any]] = []
    cases: list[dict[str, Any]] = []

    timeout = aiohttp.ClientTimeout(total=None, sock_connect=60, sock_read=args.timeout_seconds + 60)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for pdf_path in pdf_paths:
                for target in targets:
                    render_exports = target in set(args.export_targets)
                    save_preview = render_exports or pdf_path == pdf_paths[-1]
                    try:
                        case = await _run_case(
                            session,
                            pdf_path,
                            target,
                            source_lang=args.source,
                            preview_dir=preview_dir,
                            save_preview=save_preview,
                            render_exports=render_exports,
                            timeout_seconds=args.timeout_seconds,
                        )
                        cases.append(case)
                        print(json.dumps({"case": case}, ensure_ascii=False, default=_json_default), flush=True)
                    except Exception as exc:
                        failure = {"file": pdf_path.name, "target": target, "error": str(exc)}
                        failures.append(failure)
                        print(json.dumps({"failure": failure}, ensure_ascii=False), flush=True)
    finally:
        await _stop_server(server)

    warning_cases = [
        case
        for case in cases
        if case.get("qualityWarnings") or not case.get("previewBytes")
    ]
    summary = {
        "status": "fail" if failures else "warn" if warning_cases else "ok",
        "inputs": [path.name for path in pdf_paths],
        "targets": targets,
        "cases": len(cases),
        "failures": failures,
        "warningCases": warning_cases,
        "elapsedSeconds": round(time.monotonic() - started_at, 1),
        "previewDir": str(preview_dir),
    }
    print(json.dumps({"summary": summary}, ensure_ascii=False, indent=2, default=_json_default), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
