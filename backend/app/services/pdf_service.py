import fitz
import os
import uuid
from typing import List, Dict, Any

class PDFService:
    def __init__(self):
        self.upload_dir = "uploads"
        self.output_dir = "outputs"
        os.makedirs(self.upload_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)
    
    def save_uploaded_file(self, file_content: bytes) -> str:
        file_id = str(uuid.uuid4())
        file_path = os.path.join(self.upload_dir, f"{file_id}.pdf")
        with open(file_path, "wb") as f:
            f.write(file_content)
        return file_id
    
    def get_file_path(self, file_id: str) -> str:
        return os.path.join(self.upload_dir, f"{file_id}.pdf")
    
    def get_output_path(self, task_id: str) -> str:
        return os.path.join(self.output_dir, f"{task_id}.json")
    
    def get_total_pages(self, file_id: str) -> int:
        file_path = self.get_file_path(file_id)
        if not os.path.exists(file_path):
            raise FileNotFoundError("File not found")
        
        doc = fitz.open(file_path)
        total_pages = len(doc)
        doc.close()
        return total_pages
    
    def extract_text_blocks(self, file_id: str, page_num: int) -> List[Dict[str, Any]]:
        file_path = self.get_file_path(file_id)
        if not os.path.exists(file_path):
            raise FileNotFoundError("File not found")
        
        doc = fitz.open(file_path)
        if page_num < 0 or page_num >= len(doc):
            raise ValueError("Invalid page number")
        
        page = doc[page_num]
        text_blocks = []
        
        for block in page.get_text("blocks"):
            if len(block) >= 4:
                x0, y0, x1, y1 = block[:4]
                text = block[4].strip()
                if text:
                    text_blocks.append({
                        "bbox": {"x0": x0, "y0": y0, "x1": x1, "y1": y1},
                        "text": text,
                    })
        
        doc.close()
        return text_blocks
    
    def extract_full_text(self, file_id: str, page_num: int) -> str:
        file_path = self.get_file_path(file_id)
        if not os.path.exists(file_path):
            raise FileNotFoundError("File not found")
        
        doc = fitz.open(file_path)
        if page_num < 0 or page_num >= len(doc):
            raise ValueError("Invalid page number")
        
        page = doc[page_num]
        text = page.get_text()
        doc.close()
        return text
    
    def save_translation_result(self, task_id: str, result: Dict[str, Any]):
        output_path = self.get_output_path(task_id)
        import json
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    
    def load_translation_result(self, task_id: str) -> Dict[str, Any]:
        output_path = self.get_output_path(task_id)
        if not os.path.exists(output_path):
            raise FileNotFoundError("Result not found")
        
        import json
        with open(output_path, "r", encoding="utf-8") as f:
            return json.load(f)
    
    def generate_bilingual_pdf(self, file_id: str, translation_result: Dict[str, Any]) -> bytes:
        input_path = self.get_file_path(file_id)
        if not os.path.exists(input_path):
            raise FileNotFoundError("File not found")
        
        doc = fitz.open(input_path)
        
        for page_data in translation_result["pages"]:
            page_num = page_data["pageNum"] - 1
            if page_num >= len(doc):
                continue
            
            page = doc[page_num]
            for block in page_data.get("textBlocks", []):
                bbox = block["bbox"]
                translated_text = block["translatedText"]
                
                rect = fitz.Rect(bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"])
                page.add_redact_annot(rect)
                page.apply_redactions()
                
                font_size = (bbox["y1"] - bbox["y0"]) * 0.8
                page.insert_text(
                    (bbox["x0"], bbox["y1"] - 2),
                    translated_text,
                    fontsize=font_size,
                    color=fitz.utils.getColor("black"),
                )
        
        output_buffer = bytearray()
        doc.save(output_buffer)
        doc.close()
        
        return bytes(output_buffer)
