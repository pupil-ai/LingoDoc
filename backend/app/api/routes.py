from fastapi import APIRouter, File, UploadFile, HTTPException, BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse, FileResponse, Response
from pydantic import BaseModel
from typing import Dict, Any, Optional
import uuid
import asyncio
import os
import hashlib
import hmac
import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

from app.services.pdf_service import PDFService
from app.services.pdf_quality_service import build_pdf_quality_report
from app.services.translate_service import (
    SUPPORTED_LANGUAGE_CODES,
    TranslationServiceFactory,
    get_translation_model_for_plan,
    safe_print,
)
from app.services.translation_text_utils import sanitize_translated_text
from app.services.db_service import db_service
from app.services.storage_service import storage_service
from app.services.plan_service import (
    PlanLimits,
    get_max_file_size_bytes,
    get_plan_limits,
    get_translatable_page_count,
)
from app.api.auth import CurrentUser, get_current_user, get_optional_current_user

router = APIRouter()

pdf_service = PDFService()
translation_tasks: Dict[str, Dict[str, Any]] = {}
export_tasks: Dict[str, Dict[str, Any]] = {}


def _env_int(name: str, default: int, *, minimum: int = 1, maximum: int = 100) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(min(value, maximum), minimum)


def _env_float(name: str, default: float, *, minimum: float = 0.1, maximum: float = 100.0) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(min(value, maximum), minimum)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "off", "no"}


TRANSLATION_BATCH_MAX_BLOCKS = _env_int("TRANSLATION_BATCH_MAX_BLOCKS", 20, minimum=1, maximum=80)
TRANSLATION_BATCH_MAX_CHARS = _env_int("TRANSLATION_BATCH_MAX_CHARS", 8000, minimum=500, maximum=30000)
TRANSLATION_BATCH_CONCURRENCY = _env_int("TRANSLATION_BATCH_CONCURRENCY", 3, minimum=1, maximum=20)
TRANSLATION_FALLBACK_CONCURRENCY = _env_int("TRANSLATION_FALLBACK_CONCURRENCY", 3, minimum=1, maximum=12)
PAGE_TRANSLATION_CONCURRENCY = _env_int("PAGE_TRANSLATION_CONCURRENCY", 6, minimum=1, maximum=50)
PAGE_RETRY_LIMIT = _env_int("PAGE_RETRY_LIMIT", 2, minimum=0, maximum=5)
EXPORT_SIZE_WARN_RATIO = _env_float("EXPORT_SIZE_WARN_RATIO", 2.2, minimum=1.0, maximum=20.0)
AUTO_PREPARE_EXPORTS = _env_bool("AUTO_PREPARE_EXPORTS", True)
AUTO_PREPARE_EXPORT_TYPES = tuple(
    output_type
    for output_type in (
        item.strip().lower()
        for item in os.getenv("AUTO_PREPARE_EXPORT_TYPES", "bilingual,translated").split(",")
    )
    if output_type in {"bilingual", "translated"}
)
PREVIEW_URL_TTL_SECONDS = 15 * 60

REFERENCE_SUPERSCRIPT_CHARS = "\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078\u2079"
REFERENCE_MARKER_RE = re.compile(
    rf"[{REFERENCE_SUPERSCRIPT_CHARS}]+(?:[,\.\-\u2013\u2014][{REFERENCE_SUPERSCRIPT_CHARS}]+)*"
)
REFERENCE_TOKEN_RE = re.compile(r"\[\[\s*REF\s*(\d+)\s*\]\]", flags=re.IGNORECASE)

class TranslationRequest(BaseModel):
    fileId: str
    sourceLang: str
    targetLang: str


SUPPORTED_LANGUAGE_SET = set(SUPPORTED_LANGUAGE_CODES)


def _normalize_supported_language(lang: str, field_name: str) -> str:
    normalized = (lang or "").strip().lower()
    if normalized not in SUPPORTED_LANGUAGE_SET:
        supported = ", ".join(SUPPORTED_LANGUAGE_CODES)
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported {field_name}. Supported languages: {supported}",
        )
    return normalized


class ExportJobRequest(BaseModel):
    outputType: str


def _export_task_key(task_id: str, output_type: str) -> str:
    return f"{task_id}:{output_type}"


def _normalize_output_type(output_type: str) -> str:
    normalized = (output_type or "").strip().lower()
    if normalized not in {"translated", "bilingual"}:
        raise HTTPException(status_code=400, detail="Invalid output_type")
    return normalized


def _build_export_size_metadata(task_id: str, file_id: str, output_type: str) -> Dict[str, Any]:
    try:
        source_path = pdf_service.get_file_path(file_id)
        export_path = pdf_service.get_cached_export_pdf_path(task_id, output_type)
        source_bytes = os.path.getsize(source_path)
        export_bytes = os.path.getsize(export_path)
    except Exception as error:
        safe_print(
            "[DEBUG] Export size metadata unavailable: "
            f"task={task_id} output_type={output_type} error={error}"
        )
        return {}

    size_ratio = export_bytes / max(source_bytes, 1)
    return {
        "sourceBytes": source_bytes,
        "exportBytes": export_bytes,
        "sizeRatio": round(size_ratio, 3),
        "sizeWarnRatio": EXPORT_SIZE_WARN_RATIO,
        "sizeWarning": size_ratio > EXPORT_SIZE_WARN_RATIO,
    }


def _build_quality_response_metadata(report: Dict[str, Any]) -> Dict[str, Any]:
    summary = report.get("summary") or {}
    return {
        "qualityStatus": report.get("status", "unknown"),
        "qualityWarnings": int(summary.get("warnings") or 0),
        "qualityWarningCounts": summary.get("warningCounts") or {},
    }


def _build_and_save_export_quality_report(
    task_id: str,
    output_type: str,
    result: Dict[str, Any],
    size_metadata: Dict[str, Any],
) -> Dict[str, Any]:
    report = build_pdf_quality_report(
        result,
        output_type=output_type,
        source_bytes=size_metadata.get("sourceBytes"),
        export_bytes=size_metadata.get("exportBytes"),
        size_warn_ratio=EXPORT_SIZE_WARN_RATIO,
    )
    pdf_service.save_export_quality_report(task_id, output_type, report)
    return report


def _get_preview_url_secret() -> str:
    return (
        os.getenv("PREVIEW_URL_SECRET", "").strip()
        or os.getenv("PADDLE_WEBHOOK_SECRET", "").strip()
        or os.getenv("R2_SECRET_ACCESS_KEY", "").strip()
    )


def _build_preview_signature(
    *,
    task_id: str,
    user_id: str,
    format: str,
    output_type: str,
    download: bool = False,
    expires_at: int,
) -> str:
    secret = _get_preview_url_secret()
    if not secret:
        raise HTTPException(status_code=503, detail="Preview URL signing is not configured")

    payload = f"{task_id}:{user_id}:{format}:{output_type}:{int(download)}:{expires_at}"
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _build_signed_preview_query(
    *,
    task_id: str,
    user_id: str,
    format: str = "pdf",
    output_type: str = "bilingual",
    download: bool = False,
) -> str:
    expires_at = int(time.time()) + PREVIEW_URL_TTL_SECONDS
    signature = _build_preview_signature(
        task_id=task_id,
        user_id=user_id,
        format=format,
        output_type=output_type,
        download=download,
        expires_at=expires_at,
    )
    query = {
        "format": format,
        "output_type": output_type,
        "preview_expires": expires_at,
        "preview_signature": signature,
    }
    if download:
        query["download"] = "true"
    return urlencode(query)


def _verify_signed_preview_request(
    *,
    task_id: str,
    task_owner_id: str,
    format: str,
    output_type: str,
    download: bool = False,
    preview_expires: Optional[int],
    preview_signature: Optional[str],
) -> bool:
    if preview_expires is None or not preview_signature:
        return False
    if preview_expires < int(time.time()):
        return False

    expected_signature = _build_preview_signature(
        task_id=task_id,
        user_id=task_owner_id,
        format=format,
        output_type=output_type,
        download=download,
        expires_at=preview_expires,
    )
    return hmac.compare_digest(expected_signature, preview_signature)


def _parse_paddle_signature(signature_header: str) -> Dict[str, str]:
    signature_parts: Dict[str, str] = {}
    for part in signature_header.split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        signature_parts[key.strip()] = value.strip()
    return signature_parts


def _verify_paddle_webhook_signature(raw_body: bytes, signature_header: str) -> None:
    webhook_secret = os.getenv("PADDLE_WEBHOOK_SECRET", "").strip()
    if not webhook_secret:
        raise HTTPException(status_code=503, detail="Paddle webhook secret is not configured")

    signature_parts = _parse_paddle_signature(signature_header)
    timestamp = signature_parts.get("ts")
    signature = signature_parts.get("h1")
    if not timestamp or not signature:
        raise HTTPException(status_code=400, detail="Missing Paddle webhook signature")

    tolerance_seconds = int(os.getenv("PADDLE_WEBHOOK_TOLERANCE_SECONDS", "300"))
    try:
        timestamp_int = int(timestamp)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Paddle webhook timestamp")

    if tolerance_seconds > 0 and abs(int(time.time()) - timestamp_int) > tolerance_seconds:
        raise HTTPException(status_code=400, detail="Expired Paddle webhook signature")

    signed_payload = f"{timestamp}:{raw_body.decode('utf-8')}".encode("utf-8")
    expected_signature = hmac.new(
        webhook_secret.encode("utf-8"),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, signature):
        raise HTTPException(status_code=400, detail="Invalid Paddle webhook signature")


def _get_nested(data: Dict[str, Any], *keys: str) -> Optional[Any]:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _get_paddle_price_id(data: Dict[str, Any]) -> Optional[str]:
    items = data.get("items")
    if isinstance(items, list) and items:
        first_item = items[0]
        price_id = _get_nested(first_item, "price", "id") or first_item.get("price_id")
        if isinstance(price_id, str) and price_id:
            return price_id

    price_id = data.get("price_id") or _get_nested(data, "price", "id")
    return price_id if isinstance(price_id, str) and price_id else None


def _get_paddle_plan(data: Dict[str, Any]) -> str:
    custom_data = data.get("custom_data")
    if isinstance(custom_data, dict):
        custom_plan = str(custom_data.get("plan") or "").strip().lower()
        if custom_plan in {"starter", "pro", "power"}:
            return custom_plan

    return "free"


def _normalize_iso_datetime(value: Any) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None

    raw_value = value.strip()
    try:
        parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _get_paddle_current_period(data: Dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    period = (
        data.get("current_billing_period")
        or data.get("billing_period")
        or data.get("current_period")
    )
    starts_at = None
    ends_at = None
    if isinstance(period, dict):
        starts_at = period.get("starts_at") or period.get("start_at") or period.get("started_at")
        ends_at = period.get("ends_at") or period.get("end_at") or period.get("ended_at")

    return _normalize_iso_datetime(starts_at), _normalize_iso_datetime(ends_at)


def _get_paddle_user_id(data: Dict[str, Any]) -> Optional[str]:
    custom_data = data.get("custom_data")
    if not isinstance(custom_data, dict):
        return None

    user_id = custom_data.get("userId") or custom_data.get("user_id")
    return user_id if isinstance(user_id, str) and user_id else None

def _raise_not_found() -> None:
    raise HTTPException(status_code=404, detail="Not found")


def _get_user_email(current_user: CurrentUser) -> str:
    claims = current_user.claims
    return (
        claims.get("email")
        or claims.get("email_address")
        or claims.get("primary_email_address")
        or ""
    )


def _sync_current_user(current_user: CurrentUser) -> None:
    db_service.upsert_user(current_user.id, _get_user_email(current_user) or None)


def _get_user_plan_metadata(user_id: str) -> tuple[Dict[str, Any], PlanLimits]:
    user_record = db_service.get_user(user_id) or {}
    limits = get_plan_limits(
        user_record.get("plan"),
        user_record.get("subscription_status"),
    )
    return (
        {
            "plan": limits.plan,
            "maxPagesPerFile": limits.max_pages_per_file,
            "maxFileSizeMB": limits.max_file_size_mb,
            "monthlyPageQuota": limits.monthly_page_quota,
            "freePreviewPages": limits.free_preview_pages,
            "usagePeriodStart": (
                user_record.get("paddle_current_period_start")
                or user_record.get("paddle_subscription_updated_at")
            ),
            "usagePeriodEnd": user_record.get("paddle_current_period_end"),
        },
        limits,
    )


def _get_page_translation_limit(total_pages: int, user_id: str) -> tuple[int, Dict[str, Any]]:
    plan_metadata, limits = _get_user_plan_metadata(user_id)
    return get_translatable_page_count(total_pages, limits), plan_metadata


def _get_usage_summary(user_id: str) -> Dict[str, Any]:
    plan_metadata, limits = _get_user_plan_metadata(user_id)
    usage_month = db_service.get_current_usage_month()
    usage_period_start = plan_metadata.get("usagePeriodStart") if limits.plan != "free" else None
    used_pages = db_service.get_user_monthly_usage(
        user_id,
        usage_month,
        created_at_gte=usage_period_start,
        plan="free" if limits.plan == "free" else None,
    )
    monthly_quota = limits.monthly_page_quota
    remaining_pages = max(monthly_quota - used_pages, 0) if monthly_quota > 0 else None

    return {
        **plan_metadata,
        "usageMonth": usage_month,
        "usedPages": used_pages,
        "remainingPages": remaining_pages,
        "monthlyPageQuota": monthly_quota,
    }


def _authorize_translation_request(total_pages: int, user_id: str) -> tuple[int, Dict[str, Any]]:
    plan_metadata = _get_usage_summary(user_id)
    limits = get_plan_limits(plan_metadata["plan"], "active" if plan_metadata["plan"] != "free" else "inactive")
    monthly_quota = plan_metadata["monthlyPageQuota"]
    remaining_pages = plan_metadata["remainingPages"]

    if remaining_pages is not None and remaining_pages <= 0:
        raise HTTPException(
            status_code=402,
            detail=(
                f"You have used all {monthly_quota} pages in your {plan_metadata['plan']} "
                f"plan for {plan_metadata['usageMonth']}. Please upgrade or wait until next month."
            ),
        )

    if limits.plan == "free":
        preview_pages = get_translatable_page_count(total_pages, limits)
        pages_to_translate = min(preview_pages, remaining_pages) if remaining_pages is not None else preview_pages
        if pages_to_translate <= 0:
            raise HTTPException(status_code=402, detail="No free preview pages remaining this month.")
        return pages_to_translate, plan_metadata

    if not limits.is_unlimited_pages and total_pages > limits.max_pages_per_file:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Your {plan_metadata['plan']} plan supports PDFs up to "
                f"{limits.max_pages_per_file} pages per file."
            ),
        )

    if remaining_pages is not None and total_pages > remaining_pages:
        raise HTTPException(
            status_code=402,
            detail=(
                f"This PDF needs {total_pages} pages, but your {plan_metadata['plan']} "
                f"plan has {remaining_pages} pages remaining for {plan_metadata['usageMonth']}."
            ),
        )

    return total_pages, plan_metadata


def _build_page_translated_text(translated_blocks: list[Dict[str, Any]]) -> str:
    translated_parts = [
        block.get("translatedText", "").strip()
        for block in translated_blocks
        if (
            block.get("type") == "text"
            and not block.get("is_header_footer_metadata")
            and block.get("translatedText", "").strip()
        )
    ]
    return "\n".join(translated_parts)


def _chunk_translatable_blocks(blocks: list[Dict[str, Any]]) -> list[list[tuple[int, Dict[str, Any]]]]:
    batches: list[list[tuple[int, Dict[str, Any]]]] = []
    current_batch: list[tuple[int, Dict[str, Any]]] = []
    current_chars = 0

    for index, block in enumerate(blocks):
        if (
            block.get("type") != "text"
            or block.get("is_header_footer_metadata")
            or not pdf_service.is_translatable_text_block(block)
        ):
            continue

        block_text = str(block.get("text") or "")
        if not block_text.strip():
            continue

        should_flush = (
            current_batch
            and (
                len(current_batch) >= TRANSLATION_BATCH_MAX_BLOCKS
                or current_chars + len(block_text) > TRANSLATION_BATCH_MAX_CHARS
            )
        )
        if should_flush:
            batches.append(current_batch)
            current_batch = []
            current_chars = 0

        current_batch.append((index, block))
        current_chars += len(block_text)

    if current_batch:
        batches.append(current_batch)

    return batches


def _leading_layout_marker(text: str) -> str:
    stripped = text.lstrip()
    marker_match = re.match(
        r"^((?:[\*\u2022\u00b7\-–—]\s+)|(?:\(?[A-Za-z0-9ivxlcdmIVXLCDM]{1,8}[\).]\s+))",
        stripped,
    )
    return marker_match.group(1) if marker_match else ""


def _looks_like_heading_block(block: Dict[str, Any]) -> bool:
    text = str(block.get("text") or "").strip()
    if not text or len(text) > 140:
        return False
    lines = [
        line for line in block.get("lines", [])
        if str(line.get("text") or "").strip()
    ]
    if len(lines) != 1:
        return False
    word_count = len(re.findall(r"[\w]+(?:[-/][\w]+)*", text, flags=re.UNICODE))
    if word_count > 16:
        return False
    return not text.endswith((".", "!", "?", ";", ":", "。", "！", "？", "；", "："))


def _translation_role_for_block(block: Dict[str, Any]) -> str:
    layout_role = str(block.get("layout_role") or "body")
    if layout_role != "body":
        return layout_role

    text = str(block.get("text") or "").strip()
    if _leading_layout_marker(text):
        return "list_item"
    if re.match(r"^(figure|fig\.?|table)\s+\w+", text, flags=re.IGNORECASE):
        return "caption"
    if _looks_like_heading_block(block):
        return "heading"
    return "body"


def _extract_reference_markers(text: str) -> list[str]:
    return REFERENCE_MARKER_RE.findall(text or "")


def _protect_reference_markers(text: str) -> str:
    markers: list[str] = []

    def replace_marker(match: re.Match[str]) -> str:
        token = f"[[REF{len(markers)}]]"
        markers.append(match.group(0))
        return token

    return REFERENCE_MARKER_RE.sub(replace_marker, text or "")


def _insert_before_terminal_punctuation(text: str, suffix: str) -> str:
    if not text:
        return suffix

    match = re.search(r"([,.;:!?，。；：！？、\s]+)$", text)
    if not match:
        return f"{text}{suffix}"

    return f"{text[:match.start()]}{suffix}{match.group(1)}"


def _restore_reference_markers(translated_text: str, source_text: str) -> str:
    source_markers = _extract_reference_markers(source_text)
    if not source_markers:
        return translated_text

    restored = translated_text
    for index, marker in enumerate(source_markers):
        restored = re.sub(
            rf"\[\[\s*REF\s*{index}\s*\]\]",
            marker,
            restored,
            flags=re.IGNORECASE,
        )

    remaining_text = restored
    missing_markers: list[str] = []
    for marker in source_markers:
        if marker in remaining_text:
            remaining_text = remaining_text.replace(marker, "", 1)
        else:
            missing_markers.append(marker)

    if missing_markers:
        restored = _insert_before_terminal_punctuation(restored, "".join(missing_markers))

    return restored


def _build_translation_item(block_index: int, block: Dict[str, Any]) -> Dict[str, Any]:
    text = str(block.get("text") or "")
    lines = [
        line for line in block.get("lines", [])
        if str(line.get("text") or "").strip()
    ]
    return {
        "id": block_index,
        "text": _protect_reference_markers(text),
        "role": _translation_role_for_block(block),
        "lineCount": max(len(lines), 1),
        "leadingMarker": _leading_layout_marker(text),
        "endsWithSentencePunctuation": text.rstrip().endswith((".", "!", "?", ";", ":", "。", "！", "？", "；", "：")),
    }


def _translation_cache_key(block: Dict[str, Any], source_lang: str, target_lang: str) -> str:
    item = _build_translation_item(-1, block)
    return json.dumps(
        {
            "source": source_lang,
            "target": target_lang,
            "role": item.get("role"),
            "text": item.get("text"),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


async def _translate_structured_batch(
    translator: Any,
    items: list[Dict[str, Any]],
    source_lang: str,
    target_lang: str,
    *,
    model: Optional[str] = None,
) -> list[str]:
    if model and hasattr(translator, "translate_structured_batch_with_model"):
        return await translator.translate_structured_batch_with_model(
            items,
            source_lang,
            target_lang,
            model=model,
        )
    return await translator.translate_structured_batch(items, source_lang, target_lang)


def _normalize_translated_block_text(
    translated_text: str,
    source_text: str,
    target_lang: Optional[str] = None,
) -> str:
    normalized = sanitize_translated_text(translated_text)
    normalized = re.sub(r"[ \t]*[\r\n]+[ \t]*", " ", normalized).strip()
    normalized = _restore_reference_markers(normalized, source_text)
    marker = _leading_layout_marker(source_text)
    if marker and normalized and not normalized.startswith(marker):
        normalized = f"{marker}{normalized}"
    return normalized


async def _translate_batch_with_fallback(
    translator: Any,
    batch: list[tuple[int, Dict[str, Any]]],
    source_lang: str,
    target_lang: str,
    *,
    page_number: Optional[int] = None,
    batch_number: Optional[int] = None,
    translation_cache: Optional[Dict[str, str]] = None,
    cache_lock: Optional[asyncio.Lock] = None,
    translation_model: Optional[str] = None,
) -> Dict[int, str]:
    texts = [str(block.get("text") or "") for _, block in batch]
    cached_translations: Dict[int, str] = {}
    uncached_batch: list[tuple[int, Dict[str, Any]]] = []
    if translation_cache is not None:
        for block_index, block in batch:
            cache_key = _translation_cache_key(block, source_lang, target_lang)
            cached_value = translation_cache.get(cache_key)
            if cached_value is None:
                uncached_batch.append((block_index, block))
            else:
                cached_translations[block_index] = cached_value
    else:
        uncached_batch = batch

    if not uncached_batch:
        safe_print(
            "[PERF] Batch translated from cache: "
            f"page={page_number or '?'} batch={batch_number or '?'} "
            f"blocks={len(batch)} cache_hits={len(cached_translations)}"
        )
        return cached_translations

    structured_items = [
        _build_translation_item(block_index, block)
        for block_index, block in uncached_batch
    ]
    unique_items: list[Dict[str, Any]] = []
    unique_key_by_position: list[str] = []
    item_by_key: Dict[str, Dict[str, Any]] = {}
    for item in structured_items:
        key = json.dumps(
            {
                "role": item.get("role"),
                "text": item.get("text"),
                "leadingMarker": item.get("leadingMarker"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        unique_key_by_position.append(key)
        if key not in item_by_key:
            unique_item = dict(item)
            unique_item["id"] = len(unique_items)
            item_by_key[key] = unique_item
            unique_items.append(unique_item)

    started_at = time.perf_counter()
    try:
        unique_translations = await _translate_structured_batch(
            translator,
            unique_items,
            source_lang,
            target_lang,
            model=translation_model,
        )
        if len(unique_translations) != len(unique_items):
            raise ValueError("Batch translation count mismatch")
        translated_by_key = {
            key: unique_translations[item_by_key[key]["id"]]
            for key in item_by_key
        }
        translations = [translated_by_key[key] for key in unique_key_by_position]
        safe_print(
            "[PERF] Batch translated: "
            f"page={page_number or '?'} batch={batch_number or '?'} "
            f"blocks={len(batch)} unique_blocks={len(unique_items)} cache_hits={len(cached_translations)} "
            f"chars={sum(len(text) for text in texts)} "
            f"elapsed_ms={(time.perf_counter() - started_at) * 1000:.0f}"
        )
        translated = {
            uncached_batch[index][0]: translations[index]
            for index in range(len(uncached_batch))
        }
        if translation_cache is not None:
            if cache_lock is not None:
                async with cache_lock:
                    for block_index, block in uncached_batch:
                        translation_cache[_translation_cache_key(block, source_lang, target_lang)] = translated[block_index]
            else:
                for block_index, block in uncached_batch:
                    translation_cache[_translation_cache_key(block, source_lang, target_lang)] = translated[block_index]
        translated.update(cached_translations)
        return translated
    except Exception as batch_error:
        safe_print(
            "[DEBUG] Batch translation fallback triggered: "
            f"page={page_number or '?'} batch={batch_number or '?'} error={batch_error}"
        )
        fallback_semaphore = asyncio.Semaphore(TRANSLATION_FALLBACK_CONCURRENCY)

        async def translate_one(block_index: int, block: Dict[str, Any]) -> tuple[int, str]:
            async with fallback_semaphore:
                item = _build_translation_item(block_index, block)
                translations = await _translate_structured_batch(
                    translator,
                    [item],
                    source_lang,
                    target_lang,
                    model=translation_model,
                )
                return block_index, translations[0] if translations else str(block.get("text") or "")

        translated_items = await asyncio.gather(
            *(translate_one(block_index, block) for block_index, block in uncached_batch)
        )
        translated = dict(translated_items)
        if translation_cache is not None:
            if cache_lock is not None:
                async with cache_lock:
                    for block_index, block in uncached_batch:
                        translation_cache[_translation_cache_key(block, source_lang, target_lang)] = translated[block_index]
            else:
                for block_index, block in uncached_batch:
                    translation_cache[_translation_cache_key(block, source_lang, target_lang)] = translated[block_index]
        translated.update(cached_translations)
        safe_print(
            "[PERF] Batch fallback translated: "
            f"page={page_number or '?'} batch={batch_number or '?'} "
            f"blocks={len(batch)} cache_hits={len(cached_translations)} chars={sum(len(text) for text in texts)} "
            f"elapsed_ms={(time.perf_counter() - started_at) * 1000:.0f}"
        )
        return translated


async def _translate_page_blocks(
    translator: Any,
    text_blocks: list[Dict[str, Any]],
    source_lang: str,
    target_lang: str,
    *,
    page_number: Optional[int] = None,
    translation_cache: Optional[Dict[str, str]] = None,
    cache_lock: Optional[asyncio.Lock] = None,
    translation_model: Optional[str] = None,
) -> list[Dict[str, Any]]:
    translated_blocks = [dict(block) for block in text_blocks]
    batches = _chunk_translatable_blocks(translated_blocks)
    if not batches:
        for block in translated_blocks:
            block.setdefault("translatedText", "")
        return translated_blocks

    semaphore = asyncio.Semaphore(TRANSLATION_BATCH_CONCURRENCY)

    async def run_batch(batch_index: int, batch: list[tuple[int, Dict[str, Any]]]) -> Dict[int, str]:
        async with semaphore:
            return await _translate_batch_with_fallback(
                translator,
                batch,
                source_lang,
                target_lang,
                page_number=page_number,
                batch_number=batch_index + 1,
                translation_cache=translation_cache,
                cache_lock=cache_lock,
                translation_model=translation_model,
            )

    batch_results = await asyncio.gather(*(run_batch(index, batch) for index, batch in enumerate(batches)))
    translated_text_by_index: Dict[int, str] = {}
    for batch_result in batch_results:
        translated_text_by_index.update(batch_result)

    for index, block in enumerate(translated_blocks):
        if block.get("type") == "image":
            block["translatedText"] = ""
        elif not pdf_service.is_translatable_text_block(block):
            block["translatedText"] = ""
            block["is_formula"] = block.get("is_formula", False)
        elif block.get("is_header_footer_metadata"):
            block["translatedText"] = ""
        else:
            source_text = str(block.get("text") or "")
            raw_translated_text = translated_text_by_index.get(index, source_text)
            block["translatedText"] = _normalize_translated_block_text(raw_translated_text, source_text, target_lang)
            block["is_formula"] = False

    return translated_blocks


def _build_page_result(page_num: int, full_text: str, translated_blocks: list[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "pageNum": page_num + 1,
        "original": full_text,
        "translated": _build_page_translated_text(translated_blocks),
        "textBlocks": translated_blocks,
    }


def _update_task_runtime_state(
    task_id: str,
    *,
    status: str,
    progress: float,
    processed_pages: int,
    total_pages: int,
    requested_pages: int,
    translated_pages: int,
    is_partial: bool,
    error: Optional[str] = None,
) -> None:
    current = translation_tasks.setdefault(task_id, {})
    current.update({
        "status": status,
        "progress": progress,
        "processedPages": processed_pages,
        "totalPages": total_pages,
        "requestedPages": requested_pages,
        "translatedPages": translated_pages,
        "isPartial": is_partial,
    })
    if error:
        current["error"] = error
    elif "error" in current:
        current.pop("error")


def _sync_task_progress(task_id: str, *, total_pages: int, requested_pages: int, is_partial: bool, status: str) -> Dict[str, int]:
    counts = db_service.get_task_page_counts(task_id)
    translated_pages = counts.get("completed", 0)
    processed_pages = translated_pages + counts.get("failed", 0)
    progress = (translated_pages / max(requested_pages, 1)) * 100
    db_service.update_translation_task(
        task_id,
        status=status,
        progress=progress,
        processed_pages=processed_pages,
        translated_pages=translated_pages,
        total_pages=total_pages,
        requested_pages=requested_pages,
        is_partial=is_partial,
        error=None,
    )
    _update_task_runtime_state(
        task_id,
        status=status,
        progress=progress,
        processed_pages=processed_pages,
        total_pages=total_pages,
        requested_pages=requested_pages,
        translated_pages=translated_pages,
        is_partial=is_partial,
    )
    return counts


async def _process_translation_page(
    *,
    task_id: str,
    file_id: str,
    page_number: int,
    initial_retry_count: int,
    translator: Any,
    source_lang: str,
    target_lang: str,
    user_id: str,
    plan_metadata: Dict[str, Any],
    translation_cache: Optional[Dict[str, str]] = None,
    cache_lock: Optional[asyncio.Lock] = None,
    translation_model: Optional[str] = None,
) -> None:
    attempts = initial_retry_count
    usage_reserved = False

    while attempts <= PAGE_RETRY_LIMIT:
        db_service.update_task_page(
            task_id,
            page_number,
            status="processing",
            retry_count=attempts,
            last_error="",
            started_at=str(time.time()),
        )
        page_started_at = time.perf_counter()
        try:
            if not usage_reserved:
                usage_reserved = db_service.reserve_page_usage_event(
                    task_id=task_id,
                    file_id=file_id,
                    user_id=user_id,
                    plan=plan_metadata["plan"],
                    page_number=page_number,
                    usage_month=plan_metadata.get("usageMonth"),
                    monthly_page_quota=plan_metadata.get("monthlyPageQuota"),
                    created_at_gte=plan_metadata.get("usagePeriodStart"),
                    usage_plan="free" if plan_metadata.get("plan") == "free" else None,
                )
                if not usage_reserved:
                    raise RuntimeError(
                        f"Monthly page quota reached for your {plan_metadata['plan']} plan."
                    )
                db_service.update_task_page(task_id, page_number, is_billed=True)

            extract_started_at = time.perf_counter()
            page_content = pdf_service.extract_page_content(file_id, page_number - 1)
            safe_print(
                "[PERF] Page extracted: "
                f"page={page_number} blocks={len(page_content['textBlocks'])} "
                f"elapsed_ms={(time.perf_counter() - extract_started_at) * 1000:.0f}"
            )
            translated_blocks = await _translate_page_blocks(
                translator,
                page_content["textBlocks"],
                source_lang,
                target_lang,
                page_number=page_number,
                translation_cache=translation_cache,
                cache_lock=cache_lock,
                translation_model=translation_model,
            )
            page_result = _build_page_result(
                page_number - 1,
                page_content["fullText"],
                translated_blocks,
            )
            pdf_service.save_page_translation_result(task_id, page_number - 1, page_result)
            db_service.update_task_page(
                task_id,
                page_number,
                status="completed",
                retry_count=attempts,
                last_error="",
                completed_at=str(time.time()),
            )
            safe_print(
                "[PERF] Page translated: "
                f"page={page_number} elapsed_ms={(time.perf_counter() - page_started_at) * 1000:.0f}"
            )
            return
        except Exception as page_error:
            attempts += 1
            safe_print(f"[DEBUG] Page {page_number} translation failed: {page_error}")
            if attempts > PAGE_RETRY_LIMIT:
                if usage_reserved:
                    db_service.delete_page_usage_event(task_id, page_number)
                    db_service.update_task_page(task_id, page_number, is_billed=False)
                db_service.update_task_page(
                    task_id,
                    page_number,
                    status="failed",
                    retry_count=attempts,
                    last_error=str(page_error),
                )
            else:
                db_service.update_task_page(
                    task_id,
                    page_number,
                    status="pending",
                    retry_count=attempts,
                    last_error=str(page_error),
                )

    safe_print(f"[DEBUG] Page {page_number} exhausted retries")


def _ensure_file_owner(file_id: str, user_id: str) -> Dict[str, Any]:
    file_record = db_service.get_file(file_id)
    if not file_record or file_record.get("user_id") != user_id:
        _raise_not_found()
    return file_record


def _ensure_task_owner(task_id: str, user_id: str) -> Dict[str, Any]:
    task_record = db_service.get_translation_task(task_id)
    if task_record:
        if task_record.get("user_id") != user_id:
            _raise_not_found()
        return task_record

    task = translation_tasks.get(task_id)
    if task:
        if task.get("userId") != user_id:
            _raise_not_found()
        return task

    _raise_not_found()


@router.post("/api/billing/paddle/webhook")
async def paddle_webhook(request: Request):
    raw_body = await request.body()
    signature_header = request.headers.get("Paddle-Signature", "")
    _verify_paddle_webhook_signature(raw_body, signature_header)

    try:
        event = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid Paddle webhook payload")

    event_id = str(event.get("event_id") or event.get("id") or "")
    event_type = str(event.get("event_type") or "")
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    if not event_id or not event_type:
        raise HTTPException(status_code=400, detail="Invalid Paddle webhook event")

    if db_service.has_processed_paddle_event(event_id):
        safe_print(f"[PADDLE] Duplicate webhook ignored: event_id={event_id}, type={event_type}")
        return JSONResponse({"success": True, "duplicate": True})

    if event_type.startswith("subscription."):
        user_id = _get_paddle_user_id(data)
        if user_id:
            price_id = _get_paddle_price_id(data)
            plan = _get_paddle_plan(data)
            subscription_status = str(data.get("status") or "inactive").strip().lower()
            if subscription_status in {"canceled", "cancelled", "paused", "deleted"}:
                plan = "free"
                subscription_status = "inactive"

            period_start, period_end = _get_paddle_current_period(data)
            db_service.update_user_subscription(
                user_id=user_id,
                plan=plan,
                subscription_status=subscription_status,
                paddle_customer_id=data.get("customer_id"),
                paddle_subscription_id=data.get("id"),
                paddle_price_id=price_id,
                paddle_current_period_start=period_start,
                paddle_current_period_end=period_end,
            )
            safe_print(
                "[PADDLE] Subscription synced: "
                f"event_id={event_id}, type={event_type}, user_id={user_id}, "
                f"plan={plan}, status={subscription_status}, price_id={price_id or 'unknown'}"
            )
        else:
            safe_print(
                f"[PADDLE] Subscription webhook has no Clerk user id: event_id={event_id}, type={event_type}"
            )

    db_service.record_paddle_event(event_id, event_type)
    if not event_type.startswith("subscription."):
        safe_print(f"[PADDLE] Webhook received: event_id={event_id}, type={event_type}")
    return JSONResponse({"success": True})


@router.post("/api/upload")
async def upload_file(file: UploadFile = File(...), current_user: CurrentUser = Depends(get_current_user)):
    filename = file.filename or ""
    if file.content_type != "application/pdf" and not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")
    
    try:
        _sync_current_user(current_user)
        content = await file.read()
        if not content.startswith(b"%PDF"):
            raise HTTPException(status_code=400, detail="Only PDF files are allowed")

        plan_metadata, limits = _get_user_plan_metadata(current_user.id)
        max_file_size = get_max_file_size_bytes(limits)
        if max_file_size > 0 and len(content) > max_file_size:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"Your {plan_metadata['plan']} plan supports PDF files up to "
                    f"{plan_metadata['maxFileSizeMB']} MB."
                ),
            )

        file_id = pdf_service.save_uploaded_file(content)
        total_pages = pdf_service.get_total_pages(file_id)
        db_service.create_file(
            file_id=file_id,
            user_id=current_user.id,
            original_filename=filename,
            file_size=len(content),
            total_pages=total_pages,
            storage_provider=storage_service.provider,
            storage_key=pdf_service.get_file_storage_key(file_id),
            storage_path=pdf_service.get_file_path(file_id),
        )
        
        return JSONResponse({
            "success": True,
            "fileId": file_id,
            "filename": file.filename,
            "totalPages": total_pages,
            "fileSize": len(content),
        })
    except HTTPException:
        raise
    except Exception as e:
        safe_print(f"[DEBUG] Upload failed for user={current_user.id}, filename={filename}: {str(e)}")
        if storage_service.provider == "r2":
            raise HTTPException(
                status_code=502,
                detail=(
                    "Failed to upload to Cloudflare R2. For local testing, set "
                    "STORAGE_PROVIDER=local in backend/.env and restart the backend."
                ),
            )
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/my/files")
async def list_my_files(current_user: CurrentUser = Depends(get_current_user)):
    _sync_current_user(current_user)
    files = db_service.list_user_files(current_user.id)
    return JSONResponse({
        "success": True,
        "files": files,
    })


@router.delete("/api/my/files/{file_id}")
async def delete_my_file(file_id: str, current_user: CurrentUser = Depends(get_current_user)):
    _sync_current_user(current_user)
    file_record = db_service.get_file(file_id)
    if not file_record or file_record.get("user_id") != current_user.id:
        _raise_not_found()

    task_ids = db_service.list_file_task_ids(file_id)

    storage_keys_to_delete = [file_record.get("storage_key") or pdf_service.get_file_storage_key(file_id)]
    storage_keys_to_delete.extend(
        pdf_service.get_output_storage_key(task_id)
        for task_id in task_ids
    )
    for task_id in task_ids:
        total_pages = int(file_record.get("total_pages") or 0)
        for page_num in range(total_pages):
            storage_keys_to_delete.append(pdf_service.get_output_page_storage_key(task_id, page_num))

    for storage_key in storage_keys_to_delete:
        if storage_key and storage_service.exists(storage_key):
            storage_service.delete(storage_key)

    deleted = db_service.delete_file(file_id, current_user.id)
    if not deleted:
        _raise_not_found()

    return JSONResponse({
        "success": True,
        "fileId": file_id,
    })


@router.get("/api/me/usage")
async def get_my_usage(current_user: CurrentUser = Depends(get_current_user)):
    _sync_current_user(current_user)
    return JSONResponse({
        "success": True,
        **_get_usage_summary(current_user.id),
    })


async def auto_prepare_export_pdfs(task_id: str, file_id: str, result: Dict[str, Any]) -> None:
    if not AUTO_PREPARE_EXPORTS or not AUTO_PREPARE_EXPORT_TYPES:
        return

    for output_type in AUTO_PREPARE_EXPORT_TYPES:
        job_key = _export_task_key(task_id, output_type)
        current_job = export_tasks.get(job_key)
        if pdf_service.has_cached_export_pdf(task_id, output_type):
            continue
        if current_job and current_job.get("status") in {"queued", "rendering"}:
            continue

        export_tasks[job_key] = {
            "status": "queued",
            "taskId": task_id,
            "outputType": output_type,
            "error": "",
            "autoPrepared": True,
        }
        safe_print(
            "[PERF] Auto export queued: "
            f"task={task_id} output_type={output_type}"
        )
        await render_export_pdf_task(task_id, file_id, result, output_type)


async def translate_pdf_task(
    task_id: str,
    file_id: str,
    source_lang: str,
    target_lang: str,
    user_id: str,
    pages_to_translate: int,
    plan_metadata: Dict[str, Any],
):
    try:
        translation_tasks[task_id] = {"userId": user_id}
        total_pages = pdf_service.get_total_pages(file_id)
        pages_to_translate = min(pages_to_translate, total_pages)
        is_partial = pages_to_translate < total_pages
        _update_task_runtime_state(
            task_id,
            status="processing",
            progress=0,
            processed_pages=0,
            total_pages=total_pages,
            requested_pages=pages_to_translate,
            translated_pages=0,
            is_partial=is_partial,
        )
        translation_tasks[task_id]["plan"] = plan_metadata["plan"]
        db_service.update_translation_task(
            task_id,
            status="processing",
            total_pages=total_pages,
            requested_pages=pages_to_translate,
            translated_pages=0,
            is_partial=is_partial,
            error="",
        )
        db_service.create_task_pages(task_id, pages_to_translate)
        db_service.reset_processing_task_pages(task_id)

        translator = TranslationServiceFactory.get("ofoxai")
        translation_model = get_translation_model_for_plan(plan_metadata["plan"])
        safe_print(f"[DEBUG] Translator type: {type(translator).__name__}")
        safe_print(
            "[DEBUG] Translation model selected: "
            f"task_id={task_id} plan={plan_metadata['plan']} model={translation_model}"
        )
        pending_page_rows = [
            page_row
            for page_row in db_service.list_task_pages(task_id)
            if int(page_row["page_number"]) <= pages_to_translate and page_row.get("status") != "completed"
        ]
        safe_print(
            "[PERF] Translation task starting: "
            f"task_id={task_id} pages={len(pending_page_rows)} "
            f"page_concurrency={PAGE_TRANSLATION_CONCURRENCY} batch_concurrency={TRANSLATION_BATCH_CONCURRENCY}"
        )

        page_semaphore = asyncio.Semaphore(PAGE_TRANSLATION_CONCURRENCY)
        translation_cache: Dict[str, str] = {}
        translation_cache_lock = asyncio.Lock()

        async def run_page(page_row: Dict[str, Any]) -> None:
            page_number = int(page_row["page_number"])
            async with page_semaphore:
                await _process_translation_page(
                    task_id=task_id,
                    file_id=file_id,
                    page_number=page_number,
                    initial_retry_count=int(page_row.get("retry_count") or 0),
                    translator=translator,
                    source_lang=source_lang,
                    target_lang=target_lang,
                    user_id=user_id,
                    plan_metadata=plan_metadata,
                    translation_cache=translation_cache,
                    cache_lock=translation_cache_lock,
                    translation_model=translation_model,
                )
                _sync_task_progress(
                    task_id,
                    total_pages=total_pages,
                    requested_pages=pages_to_translate,
                    is_partial=is_partial,
                    status="processing",
                )

        await asyncio.gather(*(run_page(page_row) for page_row in pending_page_rows))

        counts = db_service.get_task_page_counts(task_id)
        if counts.get("completed", 0) >= pages_to_translate:
            result = {
                "fileId": file_id,
                "userId": user_id,
                "totalPages": total_pages,
                "translatedPages": counts.get("completed", 0),
                "isPartial": is_partial,
                "plan": plan_metadata["plan"],
                "pageLimit": plan_metadata["maxPagesPerFile"],
                "usageMonth": plan_metadata.get("usageMonth"),
                "monthlyPageQuota": plan_metadata.get("monthlyPageQuota"),
            }
            pdf_service.save_translation_result(task_id, result)
            db_service.update_translation_task(
                task_id,
                status="completed",
                progress=100,
                processed_pages=pages_to_translate,
                translated_pages=pages_to_translate,
                total_pages=total_pages,
                requested_pages=pages_to_translate,
                is_partial=is_partial,
                error="",
            )
            _update_task_runtime_state(
                task_id,
                status="completed",
                progress=100,
                processed_pages=pages_to_translate,
                total_pages=total_pages,
                requested_pages=pages_to_translate,
                translated_pages=pages_to_translate,
                is_partial=is_partial,
            )
            asyncio.create_task(auto_prepare_export_pdfs(task_id, file_id, result))
        else:
            _sync_task_progress(
                task_id,
                total_pages=total_pages,
                requested_pages=pages_to_translate,
                is_partial=is_partial,
                status="recoverable",
            )
    except Exception as e:
        if task_id in translation_tasks:
            translation_tasks[task_id]["status"] = "error"
            translation_tasks[task_id]["error"] = str(e)
        db_service.update_translation_task(task_id, status="error", error=str(e))

@router.post("/api/translate")
async def start_translation(
    request: TranslationRequest,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(get_current_user),
):
    _sync_current_user(current_user)
    _ensure_file_owner(request.fileId, current_user.id)
    source_lang = _normalize_supported_language(request.sourceLang, "sourceLang")
    target_lang = _normalize_supported_language(request.targetLang, "targetLang")

    try:
        total_pages = pdf_service.get_total_pages(request.fileId)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")

    resumable_task = db_service.find_resumable_translation_task(
        file_id=request.fileId,
        user_id=current_user.id,
        source_lang=source_lang,
        target_lang=target_lang,
    )
    if resumable_task:
        task_id = str(resumable_task["id"])
        requested_pages = int(resumable_task.get("requested_pages") or total_pages)
        counts = db_service.get_task_page_counts(task_id)
        remaining_pages_to_run = max(requested_pages - counts.get("completed", 0), 0)
        usage_summary = _get_usage_summary(current_user.id)
        remaining_pages = usage_summary.get("remainingPages")
        if remaining_pages is not None and remaining_pages_to_run > remaining_pages:
            raise HTTPException(
                status_code=402,
                detail=(
                    f"This task still needs {remaining_pages_to_run} pages, but your "
                    f"{usage_summary['plan']} plan has {remaining_pages} pages remaining for "
                    f"{usage_summary['usageMonth']}."
                ),
            )

        plan_metadata, _ = _get_user_plan_metadata(current_user.id)
        plan_metadata.update({
            "usageMonth": usage_summary.get("usageMonth"),
            "monthlyPageQuota": usage_summary.get("monthlyPageQuota"),
            "remainingPages": remaining_pages,
        })
        if task_id not in translation_tasks:
            background_tasks.add_task(
                translate_pdf_task,
                task_id,
                request.fileId,
                source_lang,
                target_lang,
                current_user.id,
                requested_pages,
                plan_metadata,
            )

        return JSONResponse({
            "success": True,
            "taskId": task_id,
            "requestedPages": requested_pages,
            "totalPages": total_pages,
            "isPartial": requested_pages < total_pages,
            "plan": plan_metadata["plan"],
            "monthlyPageQuota": plan_metadata.get("monthlyPageQuota"),
            "remainingPages": plan_metadata.get("remainingPages"),
            "resumed": True,
        })

    pages_to_translate, plan_metadata = _authorize_translation_request(total_pages, current_user.id)

    task_id = str(uuid.uuid4())
    db_service.create_translation_task(
        task_id=task_id,
        file_id=request.fileId,
        user_id=current_user.id,
        source_lang=source_lang,
        target_lang=target_lang,
    )
    background_tasks.add_task(
        translate_pdf_task,
        task_id,
        request.fileId,
        source_lang,
        target_lang,
        current_user.id,
        pages_to_translate,
        plan_metadata,
    )

    return JSONResponse({
        "success": True,
        "taskId": task_id,
        "requestedPages": pages_to_translate,
        "totalPages": total_pages,
        "isPartial": pages_to_translate < total_pages,
        "plan": plan_metadata["plan"],
        "monthlyPageQuota": plan_metadata.get("monthlyPageQuota"),
        "remainingPages": plan_metadata.get("remainingPages"),
        "resumed": False,
    })

@router.get("/api/translate/{task_id}/progress")
async def get_progress(task_id: str, current_user: CurrentUser = Depends(get_current_user)):
    task_record = _ensure_task_owner(task_id, current_user.id)

    if task_id not in translation_tasks:
        if "status" in task_record:
            requested_pages = task_record.get("requested_pages") or task_record.get("total_pages") or 0
            translated_pages = task_record.get("translated_pages") or task_record.get("processed_pages") or 0
            task_status = task_record["status"]
            if task_status == "processing":
                task_status = "recoverable"
            return JSONResponse({
                "status": task_status,
                "progress": task_record["progress"],
                "processedPages": task_record["processed_pages"],
                "totalPages": task_record["total_pages"],
                "requestedPages": requested_pages,
                "translatedPages": translated_pages,
                "isPartial": bool(task_record.get("is_partial")),
                **({"error": task_record["error"]} if task_record.get("error") else {}),
            })
        raise HTTPException(status_code=404, detail="Task not found")
    
    progress = {key: value for key, value in translation_tasks[task_id].items() if key != "userId"}
    return JSONResponse(progress)

@router.get("/api/translate/{task_id}/result")
async def get_result(
    task_id: str,
    include_pages: bool = True,
    current_user: CurrentUser = Depends(get_current_user),
):
    task_record = _ensure_task_owner(task_id, current_user.id)

    try:
        if not include_pages:
            file_id = task_record.get("file_id") or task_record.get("fileId")
            total_pages = task_record.get("total_pages") or task_record.get("totalPages")
            translated_pages = (
                task_record.get("translated_pages")
                or task_record.get("translatedPages")
                or task_record.get("processed_pages")
            )
            if file_id and total_pages is not None:
                return JSONResponse({
                    "success": True,
                    "fileId": file_id,
                    "totalPages": total_pages,
                    "translatedPages": translated_pages or 0,
                    "isPartial": bool(task_record.get("is_partial") or task_record.get("isPartial")),
                    "previewUrl": (
                        f"/api/export/{task_id}?{_build_signed_preview_query(task_id=task_id, user_id=current_user.id)}"
                    ),
                })

        result = (
            pdf_service.load_translation_result_with_pages(task_id)
            if include_pages
            else pdf_service.load_translation_result(task_id)
        )
        if result.get("userId") != current_user.id:
            _raise_not_found()
        response_result = {key: value for key, value in result.items() if key != "userId"}
        if not include_pages:
            response_result.pop("pages", None)
        response_result["previewUrl"] = (
            f"/api/export/{task_id}?{_build_signed_preview_query(task_id=task_id, user_id=current_user.id)}"
        )
        return JSONResponse({
            "success": True,
            **response_result,
        })
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Result not found")
    except Exception as e:
        safe_print(f"[DEBUG] Result load failed for task={task_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e) or "Failed to load translation result")


@router.get("/api/translate/{task_id}/pages/{page_num}/preview")
async def get_translation_page_preview(
    task_id: str,
    page_num: int,
    width: int = 1800,
    current_user: CurrentUser = Depends(get_current_user),
):
    task_record = _ensure_task_owner(task_id, current_user.id)
    if page_num < 1:
        raise HTTPException(status_code=400, detail="Invalid page number")

    try:
        file_id = task_record.get("file_id") or task_record.get("fileId")
        if not file_id:
            raise FileNotFoundError("Source file not found")

        safe_width = min(max(width, 800), 2600)
        if pdf_service.has_cached_export_pdf(task_id, "bilingual"):
            try:
                preview_bytes = pdf_service.generate_cached_export_page_preview_png(
                    task_id,
                    "bilingual",
                    page_num=page_num - 1,
                    max_width=safe_width,
                )
            except Exception as cache_error:
                safe_print(
                    "[DEBUG] Cached export page preview unavailable: "
                    f"task={task_id} page={page_num} error={cache_error}"
                )
                page_result = pdf_service.load_page_translation_result(task_id, page_num - 1)
                preview_bytes = pdf_service.generate_bilingual_page_preview_png(
                    file_id,
                    {"pages": [page_result]},
                    page_num=page_num - 1,
                    max_width=safe_width,
                )
        else:
            page_result = pdf_service.load_page_translation_result(task_id, page_num - 1)
            preview_bytes = pdf_service.generate_bilingual_page_preview_png(
                file_id,
                {"pages": [page_result]},
                page_num=page_num - 1,
                max_width=safe_width,
            )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Result not found")
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except Exception as error:
        safe_print(f"[DEBUG] Page preview failed for task={task_id}, page={page_num}: {str(error)}")
        raise HTTPException(status_code=500, detail="Failed to render page preview")

    return Response(
        preview_bytes,
        media_type="image/png",
        headers={
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )


async def render_export_pdf_task(
    task_id: str,
    file_id: str,
    result: Dict[str, Any],
    output_type: str,
) -> None:
    output_type = _normalize_output_type(output_type)
    job_key = _export_task_key(task_id, output_type)
    started_at = time.perf_counter()
    export_tasks[job_key] = {
        **export_tasks.get(job_key, {}),
        "status": "rendering",
        "taskId": task_id,
        "outputType": output_type,
        "startedAt": started_at,
        "error": "",
    }

    try:
        if not pdf_service.has_cached_export_pdf(task_id, output_type):
            safe_print(f"[PERF] Export job cache miss: task={task_id} output_type={output_type}")
            await asyncio.to_thread(pdf_service.render_cached_export_pdf, task_id, file_id, output_type)
        else:
            safe_print(f"[PERF] Export job cache hit: task={task_id} output_type={output_type}")

        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        size_metadata = _build_export_size_metadata(task_id, file_id, output_type)
        quality_report = await asyncio.to_thread(
            _build_and_save_export_quality_report,
            task_id,
            output_type,
            result,
            size_metadata,
        )
        quality_metadata = _build_quality_response_metadata(quality_report)
        export_tasks[job_key] = {
            "status": "ready",
            "taskId": task_id,
            "outputType": output_type,
            "elapsedMs": elapsed_ms,
            "downloadUrl": f"/api/export/{task_id}?format=pdf&output_type={output_type}&download=true",
            **size_metadata,
        }
        size_log = (
            f" source_bytes={size_metadata.get('sourceBytes')} "
            f"export_bytes={size_metadata.get('exportBytes')} "
            f"size_ratio={size_metadata.get('sizeRatio')}"
            if size_metadata
            else ""
        )
        safe_print(
            "[PERF] Export job ready: "
            f"task={task_id} output_type={output_type} elapsed_ms={elapsed_ms}{size_log}"
        )
        if size_metadata.get("sizeWarning"):
            safe_print(
                "[WARN] Export size ratio exceeded target: "
                f"task={task_id} output_type={output_type} "
                f"ratio={size_metadata.get('sizeRatio')} threshold={EXPORT_SIZE_WARN_RATIO}"
            )
        if quality_metadata.get("qualityWarnings"):
            safe_print(
                "[WARN] Export quality warnings: "
                f"task={task_id} output_type={output_type} "
                f"warnings={quality_metadata.get('qualityWarnings')} "
                f"codes={quality_metadata.get('qualityWarningCounts')}"
            )
    except Exception as error:
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        export_tasks[job_key] = {
            "status": "error",
            "taskId": task_id,
            "outputType": output_type,
            "elapsedMs": elapsed_ms,
            "error": str(error) or "Failed to render export PDF",
        }
        safe_print(f"[DEBUG] Export job failed: task={task_id} output_type={output_type} error={error}")


def _build_signed_download_url(task_id: str, output_type: str, user_id: str) -> str:
    return f"/api/export/{task_id}?{_build_signed_preview_query(task_id=task_id, user_id=user_id, output_type=output_type, download=True)}"


def _build_export_job_response(task_id: str, output_type: str, user_id: Optional[str] = None) -> Dict[str, Any]:
    output_type = _normalize_output_type(output_type)
    job_key = _export_task_key(task_id, output_type)
    job = export_tasks.get(job_key)
    download_url = (
        _build_signed_download_url(task_id, output_type, user_id)
        if user_id
        else f"/api/export/{task_id}?format=pdf&output_type={output_type}&download=true"
    )

    if pdf_service.has_cached_export_pdf(task_id, output_type):
        return {
            "success": True,
            "status": "ready",
            "taskId": task_id,
            "outputType": output_type,
            "downloadUrl": download_url,
            **({"elapsedMs": job["elapsedMs"]} if job and "elapsedMs" in job else {}),
            **({
                "sourceBytes": job["sourceBytes"],
                "exportBytes": job["exportBytes"],
                "sizeRatio": job["sizeRatio"],
                "sizeWarnRatio": job["sizeWarnRatio"],
                "sizeWarning": job["sizeWarning"],
            } if job and "sizeRatio" in job else {}),
        }

    if job:
        return {
            "success": True,
            "status": job.get("status", "queued"),
            "taskId": task_id,
            "outputType": output_type,
            **({"error": job["error"]} if job.get("error") else {}),
            **({"elapsedMs": job["elapsedMs"]} if "elapsedMs" in job else {}),
            **({
                "sourceBytes": job["sourceBytes"],
                "exportBytes": job["exportBytes"],
                "sizeRatio": job["sizeRatio"],
                "sizeWarnRatio": job["sizeWarnRatio"],
                "sizeWarning": job["sizeWarning"],
            } if "sizeRatio" in job else {}),
        }

    return {
        "success": True,
        "status": "missing",
        "taskId": task_id,
        "outputType": output_type,
    }


@router.post("/api/export/{task_id}/jobs")
async def start_export_job(
    task_id: str,
    request: ExportJobRequest,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(get_current_user),
):
    _ensure_task_owner(task_id, current_user.id)
    output_type = _normalize_output_type(request.outputType)

    try:
        result = pdf_service.load_translation_result(task_id)
        if result.get("userId") != current_user.id:
            _raise_not_found()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Result not found")

    file_id = result.get("fileId") or task_id
    job_key = _export_task_key(task_id, output_type)
    current_job = export_tasks.get(job_key)
    if (
        not pdf_service.has_cached_export_pdf(task_id, output_type)
        and (not current_job or current_job.get("status") not in {"queued", "rendering"})
    ):
        export_tasks[job_key] = {
            "status": "queued",
            "taskId": task_id,
            "outputType": output_type,
            "error": "",
        }
        background_tasks.add_task(render_export_pdf_task, task_id, file_id, result, output_type)

    return JSONResponse(_build_export_job_response(task_id, output_type, current_user.id))


@router.get("/api/export/{task_id}/jobs/{output_type}")
async def get_export_job(
    task_id: str,
    output_type: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    _ensure_task_owner(task_id, current_user.id)
    return JSONResponse(_build_export_job_response(task_id, output_type, current_user.id))


@router.get("/api/export/{task_id}")
async def export_translation(
    task_id: str,
    format: str = "text",
    output_type: str = "translated",
    download: bool = False,
    preview_expires: Optional[int] = None,
    preview_signature: Optional[str] = None,
    current_user: Optional[CurrentUser] = Depends(get_optional_current_user),
):
    try:
        if format == "pdf_bilingual":
            format = "pdf"
            output_type = "bilingual"
        elif format == "pdf_translated":
            format = "pdf"
            output_type = "translated"

        result = pdf_service.load_translation_result(task_id)
        task_owner_id = str(result.get("userId") or "")

        has_signed_export_access = (
            format == "pdf"
            and _verify_signed_preview_request(
                task_id=task_id,
                task_owner_id=task_owner_id,
                format=format,
                output_type=output_type,
                download=download,
                preview_expires=preview_expires,
                preview_signature=preview_signature,
            )
        )

        if current_user is not None:
            if task_owner_id != current_user.id:
                _raise_not_found()
        elif not has_signed_export_access:
            raise HTTPException(status_code=401, detail="Missing Authorization header")

        file_id = result.get("fileId") or task_id
        
        if format == "text":
            result = pdf_service.load_translation_result_with_pages(task_id)
            content = ""
            for page in result["pages"]:
                content += f"=== Page {page['pageNum']} ===\n"
                content += f"Original:\n{page['original']}\n\n"
                content += f"Translation:\n{page['translated']}\n\n"
            
            return JSONResponse({
                "success": True,
                "content": content,
            })
            
        elif format == "pdf":
            disposition_type = "attachment" if download else "inline"
            pdf_headers = {
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
                "X-Content-Type-Options": "nosniff",
            }
            if output_type in {"translated", "bilingual"}:
                export_started_at = time.perf_counter()
                if not pdf_service.has_cached_export_pdf(task_id, output_type):
                    safe_print(
                        "[PERF] Export download requested before cache ready: "
                        f"task={task_id} output_type={output_type} "
                        f"elapsed_ms={(time.perf_counter() - export_started_at) * 1000:.0f}"
                    )
                    raise HTTPException(
                        status_code=409,
                        detail="Export PDF is not ready. Start an export job before downloading.",
                    )
                else:
                    safe_print(
                        "[PERF] Export cache hit: "
                        f"task={task_id} output_type={output_type} "
                        f"elapsed_ms={(time.perf_counter() - export_started_at) * 1000:.0f}"
                    )

                export_path = pdf_service.get_cached_export_pdf_path(task_id, output_type)
                return FileResponse(
                    export_path,
                    media_type="application/pdf",
                    filename=f"{task_id}_{output_type}.pdf",
                    content_disposition_type=disposition_type,
                    headers=pdf_headers,
                )
            else:
                raise HTTPException(status_code=400, detail="Invalid output_type")
        
        else:
            raise HTTPException(status_code=400, detail="Invalid format")
    
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Result not found")


@router.get("/api/files/{file_id}")
async def get_original_file(
    file_id: str,
    download: bool = False,
    current_user: CurrentUser = Depends(get_current_user),
):
    _ensure_file_owner(file_id, current_user.id)

    file_path = pdf_service.get_file_path(file_id)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse(
        file_path,
        media_type="application/pdf",
        filename=f"{file_id}.pdf",
        content_disposition_type="attachment" if download else "inline",
    )


@router.get("/api/files/{file_id}/preview")
async def get_original_file_preview(
    file_id: str,
    page: int = 1,
    width: int = 1400,
    current_user: CurrentUser = Depends(get_current_user),
):
    _ensure_file_owner(file_id, current_user.id)
    safe_width = min(max(width, 600), 2000)

    try:
        preview_bytes = pdf_service.generate_page_preview_png(
            file_id,
            page_num=max(page - 1, 0),
            max_width=safe_width,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    return Response(
        preview_bytes,
        media_type="image/png",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-Content-Type-Options": "nosniff",
        },
    )
