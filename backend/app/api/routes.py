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
import time

from app.services.pdf_service import PDFService
from app.services.translate_service import TranslationServiceFactory, safe_print
from app.services.db_service import db_service
from app.services.storage_service import storage_service
from app.services.plan_service import (
    PlanLimits,
    get_max_file_size_bytes,
    get_plan_limits,
    get_translatable_page_count,
)
from app.api.auth import CurrentUser, get_current_user

router = APIRouter()

pdf_service = PDFService()
translation_tasks: Dict[str, Dict[str, Any]] = {}

class TranslationRequest(BaseModel):
    fileId: str
    sourceLang: str
    targetLang: str


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
        },
        limits,
    )


def _get_page_translation_limit(total_pages: int, user_id: str) -> tuple[int, Dict[str, Any]]:
    plan_metadata, limits = _get_user_plan_metadata(user_id)
    return get_translatable_page_count(total_pages, limits), plan_metadata


def _get_usage_summary(user_id: str) -> Dict[str, Any]:
    plan_metadata, limits = _get_user_plan_metadata(user_id)
    usage_month = db_service.get_current_usage_month()
    used_pages = db_service.get_user_monthly_usage(user_id, usage_month)
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
        if block.get("type") == "text" and block.get("translatedText", "").strip()
    ]
    return "\n".join(translated_parts)


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

    try:
        result = pdf_service.load_translation_result(task_id)
    except FileNotFoundError:
        _raise_not_found()

    if result.get("userId") != user_id:
        _raise_not_found()
    return result


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

            db_service.update_user_subscription(
                user_id=user_id,
                plan=plan,
                subscription_status=subscription_status,
                paddle_customer_id=data.get("customer_id"),
                paddle_subscription_id=data.get("id"),
                paddle_price_id=price_id,
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
        translation_tasks[task_id] = {
            "status": "processing",
            "progress": 0,
            "processedPages": 0,
            "totalPages": 0,
            "userId": user_id,
        }
        
        total_pages = pdf_service.get_total_pages(file_id)
        pages_to_translate = min(pages_to_translate, total_pages)
        is_partial = pages_to_translate < total_pages
        translation_tasks[task_id]["totalPages"] = total_pages
        translation_tasks[task_id]["requestedPages"] = pages_to_translate
        translation_tasks[task_id]["translatedPages"] = 0
        translation_tasks[task_id]["isPartial"] = is_partial
        translation_tasks[task_id]["plan"] = plan_metadata["plan"]
        db_service.update_translation_task(
            task_id,
            total_pages=total_pages,
            requested_pages=pages_to_translate,
            translated_pages=0,
            is_partial=is_partial,
        )
        
        translator = TranslationServiceFactory.get("ofoxai")
        safe_print(f"[DEBUG] Translator type: {type(translator).__name__}")
        result = {
            "pages": [],
            "fileId": file_id,
            "userId": user_id,
            "totalPages": total_pages,
            "translatedPages": pages_to_translate,
            "isPartial": is_partial,
            "plan": plan_metadata["plan"],
            "pageLimit": plan_metadata["maxPagesPerFile"],
            "usageMonth": plan_metadata.get("usageMonth"),
            "monthlyPageQuota": plan_metadata.get("monthlyPageQuota"),
        }
        
        for page_num in range(pages_to_translate):
            text_blocks = pdf_service.extract_text_blocks(file_id, page_num)
            full_text = pdf_service.extract_full_text(file_id, page_num)
            
            translated_blocks = []
            for block in text_blocks:
                block_type = block.get("type", "text")
                
                if block_type == "image":
                    # 图片块，不翻译
                    translated_blocks.append({
                        "type": "image",
                        "bbox": block["bbox"],
                        "text": "",
                        "translatedText": "",
                    })
                elif not pdf_service.is_translatable_text_block(block):
                    translated_blocks.append({
                        "type": "formula",
                        "bbox": block["bbox"],
                        "text": block["text"],
                        "translatedText": "",
                        "font_size": block.get("font_size"),
                        "lines": block.get("lines", []),
                        "is_formula": True,
                    })
                else:
                    # 文本块，逐块翻译
                    try:
                        translated_text = await translator.translate(
                            block["text"], source_lang, target_lang
                        )
                        translated_blocks.append({
                            "type": "text",
                            "bbox": block["bbox"],
                            "text": block["text"],
                            "translatedText": translated_text,
                            "font_size": block.get("font_size"),
                            "lines": block.get("lines", []),
                            "is_formula": False,
                        })
                    except Exception as e:
                        safe_print(f"[DEBUG] Block translation failed: {str(e)}")
                        translated_blocks.append({
                            "type": "text",
                            "bbox": block["bbox"],
                            "text": block["text"],
                            "translatedText": block["text"],
                            "font_size": block.get("font_size"),
                            "lines": block.get("lines", []),
                            "is_formula": False,
                        })
            
            # 整页翻译用于预览
            translated_full = _build_page_translated_text(translated_blocks)
            
            result["pages"].append({
                "pageNum": page_num + 1,
                "original": full_text,
                "translated": translated_full,
                "textBlocks": translated_blocks,
            })
            
            translation_tasks[task_id]["processedPages"] = page_num + 1
            translation_tasks[task_id]["translatedPages"] = page_num + 1
            translation_tasks[task_id]["progress"] = ((page_num + 1) / max(pages_to_translate, 1)) * 100
            db_service.update_translation_task(
                task_id,
                progress=translation_tasks[task_id]["progress"],
                processed_pages=page_num + 1,
                translated_pages=page_num + 1,
                total_pages=total_pages,
            )
            
            await asyncio.sleep(0.5)
        
        pdf_service.save_translation_result(task_id, result)
        db_service.record_usage_event(
            task_id=task_id,
            file_id=file_id,
            user_id=user_id,
            plan=plan_metadata["plan"],
            pages=len(result["pages"]),
            usage_month=plan_metadata.get("usageMonth"),
        )
        translation_tasks[task_id]["status"] = "completed"
        db_service.update_translation_task(
            task_id,
            status="completed",
            progress=100,
            processed_pages=pages_to_translate,
            translated_pages=pages_to_translate,
            total_pages=total_pages,
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

    try:
        total_pages = pdf_service.get_total_pages(request.fileId)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")

    pages_to_translate, plan_metadata = _authorize_translation_request(total_pages, current_user.id)
    
    task_id = str(uuid.uuid4())
    db_service.create_translation_task(
        task_id=task_id,
        file_id=request.fileId,
        user_id=current_user.id,
        source_lang=request.sourceLang,
        target_lang=request.targetLang,
    )
    background_tasks.add_task(
        translate_pdf_task,
        task_id,
        request.fileId,
        request.sourceLang,
        request.targetLang,
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
    })

@router.get("/api/translate/{task_id}/progress")
async def get_progress(task_id: str, current_user: CurrentUser = Depends(get_current_user)):
    task_record = _ensure_task_owner(task_id, current_user.id)

    if task_id not in translation_tasks:
        if "status" in task_record:
            requested_pages = task_record.get("requested_pages") or task_record.get("total_pages") or 0
            translated_pages = task_record.get("translated_pages") or task_record.get("processed_pages") or 0
            return JSONResponse({
                "status": task_record["status"],
                "progress": task_record["progress"],
                "processedPages": task_record["processed_pages"],
                "totalPages": task_record["total_pages"],
                "requestedPages": requested_pages,
                "translatedPages": translated_pages,
                "isPartial": bool(task_record.get("is_partial")),
                **({"error": task_record["error"]} if task_record.get("error") else {}),
            })

        try:
            result = pdf_service.load_translation_result(task_id)
            total_pages = result.get("totalPages", len(result["pages"]))
            translated_pages = result.get("translatedPages", len(result["pages"]))
            return JSONResponse({
                "status": "completed",
                "progress": 100,
                "processedPages": translated_pages,
                "totalPages": total_pages,
                "requestedPages": translated_pages,
                "translatedPages": translated_pages,
                "isPartial": bool(result.get("isPartial")),
            })
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Task not found")
    
    progress = {key: value for key, value in translation_tasks[task_id].items() if key != "userId"}
    return JSONResponse(progress)

@router.get("/api/translate/{task_id}/result")
async def get_result(task_id: str, current_user: CurrentUser = Depends(get_current_user)):
    _ensure_task_owner(task_id, current_user.id)

    try:
        result = pdf_service.load_translation_result(task_id)
        if result.get("userId") != current_user.id:
            _raise_not_found()
        response_result = {key: value for key, value in result.items() if key != "userId"}
        return JSONResponse({
            "success": True,
            **response_result,
        })
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Result not found")

@router.get("/api/export/{task_id}")
async def export_translation(
    task_id: str,
    format: str = "text",
    output_type: str = "translated",
    download: bool = False,
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        _ensure_task_owner(task_id, current_user.id)

        if format == "pdf_bilingual":
            format = "pdf"
            output_type = "bilingual"
        elif format == "pdf_translated":
            format = "pdf"
            output_type = "translated"

        result = pdf_service.load_translation_result(task_id)
        if result.get("userId") != current_user.id:
            _raise_not_found()
        file_id = result.get("fileId") or task_id
        
        if format == "text":
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
            if output_type == "translated":
                # 纯译文版
                pdf_bytes = pdf_service.generate_translated_pdf(file_id, result)
                return Response(
                    pdf_bytes,
                    media_type="application/pdf",
                    headers={
                        **pdf_headers,
                        "Content-Disposition": f'{disposition_type}; filename="{task_id}_translated.pdf"',
                    },
                )
            elif output_type == "bilingual":
                # 左右对照版
                pdf_bytes = pdf_service.generate_bilingual_pdf(file_id, result)
                return Response(
                    pdf_bytes,
                    media_type="application/pdf",
                    headers={
                        **pdf_headers,
                        "Content-Disposition": f'{disposition_type}; filename="{task_id}_bilingual.pdf"',
                    },
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
