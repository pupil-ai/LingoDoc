from fastapi import APIRouter, File, UploadFile, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel
from typing import Dict, Any
import uuid
import asyncio
import os

from app.services.pdf_service import PDFService
from app.services.translate_service import TranslationServiceFactory

router = APIRouter()

pdf_service = PDFService()
translation_tasks: Dict[str, Dict[str, Any]] = {}

class TranslationRequest(BaseModel):
    fileId: str
    sourceLang: str
    targetLang: str

@router.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")
    
    try:
        content = await file.read()
        file_id = pdf_service.save_uploaded_file(content)
        total_pages = pdf_service.get_total_pages(file_id)
        
        return JSONResponse({
            "success": True,
            "fileId": file_id,
            "filename": file.filename,
            "totalPages": total_pages,
            "fileSize": len(content),
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def translate_pdf_task(task_id: str, file_id: str, source_lang: str, target_lang: str):
    try:
        translation_tasks[task_id] = {
            "status": "processing",
            "progress": 0,
            "processedPages": 0,
            "totalPages": 0,
        }
        
        total_pages = pdf_service.get_total_pages(file_id)
        translation_tasks[task_id]["totalPages"] = total_pages
        
        translator = TranslationServiceFactory.get("mock")
        result = {"pages": []}
        
        for page_num in range(total_pages):
            text_blocks = pdf_service.extract_text_blocks(file_id, page_num)
            full_text = pdf_service.extract_full_text(file_id, page_num)
            
            translated_blocks = []
            for block in text_blocks:
                try:
                    translated_text = await translator.translate(
                        block["text"], source_lang, target_lang
                    )
                    translated_blocks.append({
                        "bbox": block["bbox"],
                        "text": block["text"],
                        "translatedText": translated_text,
                    })
                except Exception:
                    translated_blocks.append({
                        "bbox": block["bbox"],
                        "text": block["text"],
                        "translatedText": block["text"],
                    })
            
            try:
                translated_full = await translator.translate(full_text, source_lang, target_lang)
            except Exception:
                translated_full = full_text
            
            result["pages"].append({
                "pageNum": page_num + 1,
                "original": full_text,
                "translated": translated_full,
                "textBlocks": translated_blocks,
            })
            
            translation_tasks[task_id]["processedPages"] = page_num + 1
            translation_tasks[task_id]["progress"] = ((page_num + 1) / total_pages) * 100
            
            await asyncio.sleep(0.5)
        
        pdf_service.save_translation_result(task_id, result)
        translation_tasks[task_id]["status"] = "completed"
        
    except Exception as e:
        if task_id in translation_tasks:
            translation_tasks[task_id]["status"] = "error"
            translation_tasks[task_id]["error"] = str(e)

@router.post("/api/translate")
async def start_translation(request: TranslationRequest, background_tasks: BackgroundTasks):
    try:
        pdf_service.get_total_pages(request.fileId)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    
    task_id = str(uuid.uuid4())
    background_tasks.add_task(
        translate_pdf_task,
        task_id,
        request.fileId,
        request.sourceLang,
        request.targetLang,
    )
    
    return JSONResponse({
        "success": True,
        "taskId": task_id,
    })

@router.get("/api/translate/{task_id}/progress")
async def get_progress(task_id: str):
    if task_id not in translation_tasks:
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
    
    return JSONResponse(translation_tasks[task_id])

@router.get("/api/translate/{task_id}/result")
async def get_result(task_id: str):
    try:
        result = pdf_service.load_translation_result(task_id)
        return JSONResponse({
            "success": True,
            **result,
        })
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Result not found")

@router.get("/api/export/{task_id}")
async def export_translation(task_id: str, format: str = "text"):
    try:
        result = pdf_service.load_translation_result(task_id)
        
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
        
        elif format == "pdf_translated":
            file_id = result.get("fileId")
            if file_id:
                pdf_bytes = pdf_service.generate_bilingual_pdf(file_id, result)
                return FileResponse(
                    pdf_bytes,
                    media_type="application/pdf",
                    filename=f"{task_id}_translated.pdf",
                )
            else:
                raise HTTPException(status_code=400, detail="File ID not found")
        
        else:
            raise HTTPException(status_code=400, detail="Invalid format")
    
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Result not found")
