import fitz
import os
import uuid
from typing import List, Dict, Any


class PDFService:
    def __init__(self):
        self.upload_dir = os.path.join(os.path.dirname(__file__), "..", "..", "uploads")
        self.output_dir = os.path.join(os.path.dirname(__file__), "..", "..", "outputs")
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
        
        # 使用 get_text("dict") 获取完整的文本信息，包括字体详情
        text_info = page.get_text("dict")
        
        for block in text_info.get("blocks", []):
            block_text = ""
            block_font_size = 0
            block_x0, block_y0, block_x1, block_y1 = float('inf'), float('inf'), 0, 0
            
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    if not text:
                        continue
                    
                    # 跳过装饰性字符
                    is_decorative = (
                        len(text) == 1 and text in ["/", "-", "•", "·", "—", "–", "|", " "] or
                        (len(text) <= 2 and (span["bbox"][3] - span["bbox"][1]) < 18)
                    )
                    
                    if is_decorative:
                        continue
                    
                    block_text += text + " "
                    block_font_size = max(block_font_size, span.get("size", 0))
                    block_x0 = min(block_x0, span["bbox"][0])
                    block_y0 = min(block_y0, span["bbox"][1])
                    block_x1 = max(block_x1, span["bbox"][2])
                    block_y1 = max(block_y1, span["bbox"][3])
            
            if block_text.strip():
                text_blocks.append({
                    "type": "text",
                    "bbox": {"x0": block_x0, "y0": block_y0, "x1": block_x1, "y1": block_y1},
                    "text": block_text.strip(),
                    "font_size": block_font_size,
                })
        
        text_blocks.sort(key=lambda b: (b["bbox"]["y0"], b["bbox"]["x0"]))
        
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
    
    def generate_translated_pdf(self, file_id: str, translation_result: Dict[str, Any]) -> bytes:
        input_path = self.get_file_path(file_id)
        if not os.path.exists(input_path):
            raise FileNotFoundError("File not found")
        
        doc = fitz.open(input_path)
        
        # 查找可用的中文字体
        font_paths = [
            "C:\\Windows\\Fonts\\simhei.ttf",
            "C:\\Windows\\Fonts\\msyh.ttc",
            "C:\\Windows\\Fonts\\simkai.ttf",
        ]
        chinese_font_path = None
        for font_path in font_paths:
            if os.path.exists(font_path):
                chinese_font_path = font_path
                break
        
        for page_data in translation_result["pages"]:
            page_num = page_data["pageNum"] - 1
            if page_num >= len(doc):
                continue
            
            page = doc[page_num]
            
            # 注册中文字体到页面
            font_registered = False
            if chinese_font_path:
                try:
                    page.insert_font(fontfile=chinese_font_path, fontname="custom_chinese")
                    font_registered = True
                except Exception as e:
                    print(f"[DEBUG] Failed to register font: {str(e)}")
            
            blocks_to_process = []
            for block in page_data.get("textBlocks", []):
                if block.get("type") == "text":
                    bbox = block["bbox"]
                    rect = fitz.Rect(bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"])
                    blocks_to_process.append({
                        "rect": rect,
                        "text": block["text"],
                        "translated": block["translatedText"],
                        "height": bbox["y1"] - bbox["y0"],
                    })
            
            # 先擦除原文本
            for item in blocks_to_process:
                page.add_redact_annot(item["rect"], fill=fitz.utils.getColor("white"))
            page.apply_redactions()
            
            # 插入新的翻译文本
            for item in blocks_to_process:
                if not item["translated"]:
                    continue
                
                block_height = item["height"]
                font_size = max(block_height * 0.6, 8)
                
                # 扩展文本框确保完整显示
                rect = item["rect"]
                expanded_rect = fitz.Rect(
                    rect.x0,
                    max(0, rect.y0 - block_height * 0.3),
                    rect.x1 + 20,  # 稍微扩宽
                    min(page.rect.height, rect.y1 + block_height * 0.5)
                )
                
                try:
                    has_chinese = any('\u4e00' <= c <= '\u9fff' for c in item["translated"])
                    
                    if has_chinese and font_registered:
                        result = page.insert_textbox(
                            expanded_rect,
                            item["translated"],
                            fontsize=font_size,
                            fontname="custom_chinese",
                            color=fitz.utils.getColor("black"),
                            align=fitz.TEXT_ALIGN_LEFT,
                        )
                        if result < 0:
                            smaller_font = font_size * 0.8
                            page.insert_textbox(
                                expanded_rect,
                                item["translated"],
                                fontsize=smaller_font,
                                fontname="custom_chinese",
                                color=fitz.utils.getColor("black"),
                                align=fitz.TEXT_ALIGN_LEFT,
                            )
                    else:
                        result = page.insert_textbox(
                            expanded_rect,
                            item["translated"],
                            fontsize=font_size,
                            color=fitz.utils.getColor("black"),
                            align=fitz.TEXT_ALIGN_LEFT,
                        )
                        if result < 0:
                            smaller_font = font_size * 0.8
                            page.insert_textbox(
                                expanded_rect,
                                item["translated"],
                                fontsize=smaller_font,
                                color=fitz.utils.getColor("black"),
                                align=fitz.TEXT_ALIGN_LEFT,
                            )
                except Exception as e:
                    print(f"[DEBUG] Failed to insert translated text: {str(e)}")
                    pass
        
        pdf_bytes = doc.write()
        doc.close()
        
        return pdf_bytes
    
    def generate_bilingual_pdf(self, file_id: str, translation_result: Dict[str, Any]) -> bytes:
        input_path = self.get_file_path(file_id)
        if not os.path.exists(input_path):
            raise FileNotFoundError("File not found")
        
        src_doc = fitz.open(input_path)
        doc = fitz.open()
        
        # 查找可用的中文字体
        font_paths = [
            "C:\\Windows\\Fonts\\simhei.ttf",
            "C:\\Windows\\Fonts\\msyh.ttc",
            "C:\\Windows\\Fonts\\simkai.ttf",
        ]
        chinese_font_path = None
        for font_path in font_paths:
            if os.path.exists(font_path):
                chinese_font_path = font_path
                break
        
        for page_data in translation_result["pages"]:
            page_num = page_data["pageNum"] - 1
            if page_num >= len(src_doc):
                continue
            
            src_page = src_doc[page_num]
            original_rect = src_page.rect
            page_width = original_rect.width
            
            # 创建新的宽幅页面（左右各一半）
            new_page = doc.new_page(width=original_rect.width * 2, height=original_rect.height)
            
            # 左侧：渲染源文档页面
            left_rect = fitz.Rect(0, 0, page_width, original_rect.height)
            new_page.show_pdf_page(left_rect, src_doc, page_num)
            
            # 右侧：白色背景
            right_bg_rect = fitz.Rect(page_width, 0, page_width * 2, original_rect.height)
            new_page.draw_rect(right_bg_rect, color=fitz.utils.getColor("white"), fill=fitz.utils.getColor("white"))
            
            # 中间分隔线
            new_page.draw_line(
                (page_width, 0), (page_width, original_rect.height),
                color=fitz.utils.getColor("gray"), width=1.0
            )
            
            # 注册中文字体到页面
            font_registered = False
            if chinese_font_path:
                try:
                    new_page.insert_font(fontfile=chinese_font_path, fontname="custom_chinese")
                    font_registered = True
                except Exception as e:
                    print(f"[DEBUG] Failed to register font: {str(e)}")
            
            # 获取原文的完整文本信息（用于逐行匹配）
            text_info = src_page.get_text("dict")
            
            # 获取整页翻译结果（字段名是 translated）
            full_translation = page_data.get("translated", "")
            if not full_translation:
                # 如果没有整页翻译，使用块级翻译
                full_translation = "\n".join(
                    block["translatedText"] for block in page_data.get("textBlocks", [])
                    if block.get("type") == "text" and block.get("translatedText")
                )
            
            # 将翻译按段落分割
            translation_paragraphs = [p.strip() for p in full_translation.split('\n') if p.strip()]
            paragraph_idx = 0
            
            # 逐块写入译文，使用原文的精确字体信息
            for block in text_info.get("blocks", []):
                block_text = ""
                block_lines = []
                
                # 收集块中的所有行
                for line in block.get("lines", []):
                    line_text = ""
                    line_font_size = 0
                    line_x0, line_y0, line_x1, line_y1 = float('inf'), float('inf'), 0, 0
                    
                    for span in line.get("spans", []):
                        text = span.get("text", "").strip()
                        if not text:
                            continue
                        
                        # 跳过装饰性字符
                        is_decorative = (
                            len(text) == 1 and text in ["/", "-", "•", "·", "—", "–", "|", " "] or
                            (len(text) <= 2 and (span["bbox"][3] - span["bbox"][1]) < 18)
                        )
                        
                        if is_decorative:
                            continue
                        
                        line_text += text + " "
                        line_font_size = max(line_font_size, span.get("size", 10))
                        line_x0 = min(line_x0, span["bbox"][0])
                        line_y0 = min(line_y0, span["bbox"][1])
                        line_x1 = max(line_x1, span["bbox"][2])
                        line_y1 = max(line_y1, span["bbox"][3])
                    
                    if line_text.strip():
                        block_lines.append({
                            "text": line_text.strip(),
                            "font_size": line_font_size,
                            "x0": line_x0,
                            "y0": line_y0,
                            "x1": line_x1,
                            "y1": line_y1,
                        })
                    block_text += line_text
                
                if block_text.strip() and paragraph_idx < len(translation_paragraphs):
                    # 使用整段翻译
                    translated_text = translation_paragraphs[paragraph_idx]
                    paragraph_idx += 1
                    
                    if translated_text:
                        # 获取该块的位置和字体大小
                        if block_lines:
                            first_line = block_lines[0]
                            last_line = block_lines[-1]
                            
                            block_y0 = first_line["y0"]
                            block_y1 = last_line["y1"]
                            block_x0 = first_line["x0"]
                            block_x1 = max(line["x1"] for line in block_lines)
                            avg_font_size = sum(line["font_size"] for line in block_lines) / len(block_lines)
                            
                            # 计算右侧文本框位置（大幅扩展空间）
                            block_height = block_y1 - block_y0
                            right_rect = fitz.Rect(
                                block_x0 + page_width - 20,  # 向左扩展一点
                                block_y0 - block_height * 0.3,  # 向上扩展30%
                                page_width * 2 - 30,  # 扩展到右边距附近
                                block_y1 + block_height * 1.2  # 大幅向下扩展120%
                            )
                            
                            # 使用与原文相同的字体大小（中文稍小一点）
                            font_size = avg_font_size * 0.85
                            
                            try:
                                has_chinese = any('\u4e00' <= c <= '\u9fff' for c in translated_text)
                                
                                current_font = font_size
                                success = False
                                
                                # 尝试多次插入，逐步缩小字体
                                for attempt in range(5):
                                    if has_chinese and font_registered:
                                        result = new_page.insert_textbox(
                                            right_rect,
                                            translated_text,
                                            fontsize=current_font,
                                            fontname="custom_chinese",
                                            color=fitz.utils.getColor("black"),
                                            align=fitz.TEXT_ALIGN_LEFT,
                                        )
                                    else:
                                        result = new_page.insert_textbox(
                                            right_rect,
                                            translated_text,
                                            fontsize=current_font,
                                            color=fitz.utils.getColor("black"),
                                            align=fitz.TEXT_ALIGN_LEFT,
                                        )
                                    
                                    if result >= 0:
                                        success = True
                                        break
                                    
                                    # 缩小字体重试
                                    current_font = max(current_font * 0.85, 6)
                                
                                if not success:
                                    print(f"[DEBUG] Text truncated even after {attempt+1} attempts")
                                    
                            except Exception as e:
                                print(f"[DEBUG] Failed to insert text: {str(e)}")
                                pass
        
        pdf_bytes = doc.write()
        doc.close()
        src_doc.close()
        
        return pdf_bytes
