import os
import sys
import pathlib
import fitz
import json

# 设置环境变量
env_path = pathlib.Path(__file__).parent / ".env"
if os.path.exists(env_path):
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=env_path)

sys.path.append(os.path.join(os.path.dirname(__file__), "app"))

def safe_print(msg):
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode(sys.stdout.encoding, errors="ignore").decode(sys.stdout.encoding))

def analyze_pdf_structure():
    safe_print("=== 分析PDF文本结构 ===")
    
    from services.pdf_service import PDFService
    pdf_service = PDFService()
    
    # 加载翻译结果
    import glob
    output_files = glob.glob(os.path.join(pdf_service.output_dir, "*.json"))
    
    if not output_files:
        safe_print("❌ 没有找到翻译结果")
        return
    
    result_path = output_files[0]
    result = pdf_service.load_translation_result(os.path.basename(result_path).replace(".json", ""))
    file_id = result.get("fileId")
    
    # 打开原始PDF
    file_path = pdf_service.get_file_path(file_id)
    doc = fitz.open(file_path)
    
    # 分析第2页
    page_num = 1
    page = doc[page_num]
    safe_print(f"\n=== 第{page_num + 1}页详细分析 ===")
    
    # 获取get_text("dict")的完整信息
    text_info = page.get_text("dict")
    
    safe_print(f"\n1. Blocks数量: {len(text_info.get('blocks', []))}")
    
    total_spans = 0
    for block_idx, block in enumerate(text_info.get("blocks", [])):
        safe_print(f"\n--- Block {block_idx} ---")
        safe_print(f"   Type: {block.get('type')}")
        
        if block.get("type") == 0:  # 文本块
            safe_print(f"   BBox: {block.get('bbox')}")
            safe_print(f"   Lines数量: {len(block.get('lines', []))}")
            
            for line_idx, line in enumerate(block.get("lines", [])):
                safe_print(f"\n   Line {line_idx}:")
                safe_print(f"      BBox: {line.get('bbox')}")
                safe_print(f"      WMode: {line.get('wmode')}")
                safe_print(f"      Dir: {line.get('dir')}")
                
                for span_idx, span in enumerate(line.get("spans", [])):
                    total_spans += 1
                    text = span.get("text", "").strip()
                    if text:
                        safe_print(f"\n      Span {span_idx}:")
                        safe_print(f"         Text: {text}")
                        safe_print(f"         Font: {span.get('font')}")
                        safe_print(f"         Size: {span.get('size'):.2f}")
                        safe_print(f"         Color: {span.get('color')}")
                        safe_print(f"         BBox: {span.get('bbox')}")
                        # 可选字段
                        ascent = span.get('ascender')
                        descent = span.get('descent')
                        flags = span.get('flags')
                        if ascent is not None:
                            safe_print(f"         Ascent: {ascent:.2f}")
                        if descent is not None:
                            safe_print(f"         Descent: {descent:.2f}")
                        if flags is not None:
                            safe_print(f"         Flags: {flags}")
                            # 检查是否是粗体
                            is_bold = (flags & (1 << 0)) != 0  # 第0位是粗体
                            is_italic = (flags & (1 << 1)) != 0  # 第1位是斜体
                            safe_print(f"         Is Bold: {is_bold}")
                            safe_print(f"         Is Italic: {is_italic}")
    
    safe_print(f"\n=== 总结 ===")
    safe_print(f"总Spans数量: {total_spans}")
    
    # 保存完整的dict信息到文件以便查看
    output_file = "pdf_text_structure.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(text_info, f, ensure_ascii=False, indent=2)
    safe_print(f"\n完整结构已保存到: {os.path.abspath(output_file)}")
    
    doc.close()

if __name__ == "__main__":
    analyze_pdf_structure()
