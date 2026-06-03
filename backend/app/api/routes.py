from fastapi import APIRouter, File, UploadFile, HTTPException, BackgroundTasks, Depends
from fastapi.responses import JSONResponse, FileResponse, Response
from pydantic import BaseModel
from typing import Dict, Any
import uuid
import asyncio
import os

from app.services.pdf_service import PDFService
from app.services.translate_service import TranslationServiceFactory, safe_print
from app.services.db_service import db_service
from app.api.auth import CurrentUser, get_current_user

router = APIRouter()

pdf_service = PDFService()
translation_tasks: Dict[str, Dict[str, Any]] = {}

class TranslationRequest(BaseModel):
    fileId: str
    sourceLang: str
    targetLang: str

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


@router.post("/api/upload")
async def upload_file(file: UploadFile = File(...), current_user: CurrentUser = Depends(get_current_user)):
    _sync_current_user(current_user)

    filename = file.filename or ""
    if file.content_type != "application/pdf" and not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")
    
    try:
        content = await file.read()
        if not content.startswith(b"%PDF"):
            raise HTTPException(status_code=400, detail="Only PDF files are allowed")

        file_id = pdf_service.save_uploaded_file(content)
        total_pages = pdf_service.get_total_pages(file_id)
        db_service.create_file(
            file_id=file_id,
            user_id=current_user.id,
            original_filename=filename,
            file_size=len(content),
            total_pages=total_pages,
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
        raise HTTPException(status_code=500, detail=str(e))

async def translate_pdf_task(task_id: str, file_id: str, source_lang: str, target_lang: str, user_id: str):
    try:
        translation_tasks[task_id] = {
            "status": "processing",
            "progress": 0,
            "processedPages": 0,
            "totalPages": 0,
            "userId": user_id,
        }
        
        total_pages = pdf_service.get_total_pages(file_id)
        translation_tasks[task_id]["totalPages"] = total_pages
        db_service.update_translation_task(task_id, total_pages=total_pages)
        
        translator = TranslationServiceFactory.get("ofoxai")
        safe_print(f"[DEBUG] Translator type: {type(translator).__name__}")
        result = {"pages": [], "fileId": file_id, "userId": user_id}
        
        for page_num in range(total_pages):
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
            try:
                translated_full = await translator.translate(full_text, source_lang, target_lang)
            except Exception as e:
                safe_print(f"[DEBUG] Full text translation failed: {str(e)}")
                translated_full = full_text
            
            result["pages"].append({
                "pageNum": page_num + 1,
                "original": full_text,
                "translated": translated_full,
                "textBlocks": translated_blocks,
            })
            
            translation_tasks[task_id]["processedPages"] = page_num + 1
            translation_tasks[task_id]["progress"] = ((page_num + 1) / total_pages) * 100
            db_service.update_translation_task(
                task_id,
                progress=translation_tasks[task_id]["progress"],
                processed_pages=page_num + 1,
                total_pages=total_pages,
            )
            
            await asyncio.sleep(0.5)
        
        pdf_service.save_translation_result(task_id, result)
        translation_tasks[task_id]["status"] = "completed"
        db_service.update_translation_task(
            task_id,
            status="completed",
            progress=100,
            processed_pages=total_pages,
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
        pdf_service.get_total_pages(request.fileId)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    
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
    )
    
    return JSONResponse({
        "success": True,
        "taskId": task_id,
    })

@router.get("/api/translate/{task_id}/progress")
async def get_progress(task_id: str, current_user: CurrentUser = Depends(get_current_user)):
    task_record = _ensure_task_owner(task_id, current_user.id)

    if task_id not in translation_tasks:
        if "status" in task_record:
            return JSONResponse({
                "status": task_record["status"],
                "progress": task_record["progress"],
                "processedPages": task_record["processed_pages"],
                "totalPages": task_record["total_pages"],
                **({"error": task_record["error"]} if task_record.get("error") else {}),
            })

        try:
            result = pdf_service.load_translation_result(task_id)
            return JSONResponse({
                "status": "completed",
                "progress": 100,
                "processedPages": len(result["pages"]),
                "totalPages": len(result["pages"]),
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
