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

def safe_print(msg):
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode(sys.stdout.encoding, errors="ignore").decode(sys.stdout.encoding))

def analyze_pdf_structure():
    safe_print("=== 分析PDF文本结构 ===")
    
    # 从uploads目录找一个PDF
    upload_dir = "uploads"
    pdf_files = [f for f in os.listdir(upload_dir) if f.endswith(".pdf")]
    
    if not pdf_files:
        safe_print("❌ 没有找到PDF文件")
        return
    
    file_path = os.path.join(upload_dir, pdf_files[0])
    safe_print(f"分析文件: {file_path}")
    
    # 打开PDF
    doc = fitz.open(file_path)
    
    # 分析第2页（如果有）
    page_num = 1 if len(doc) > 1 else 0
    page = doc[page_num]
    safe_print(f"\n=== 第{page_num + 1}页详细分析 ===")
    
    # 获取get_text("dict")的完整信息
    text_info = page.get_text("dict")
    
    safe_print(f"\n1. Blocks数量: {len(text_info.get('blocks', []))}")
    
    total_spans = 0
    spans_info = []
    
    for block_idx, block in enumerate(text_info.get("blocks", [])):
        if block.get("type") == 0:  # 文本块
            for line_idx, line in enumerate(block.get("lines", [])):
                for span_idx, span in enumerate(line.get("spans", [])):
                    text = span.get("text", "").strip()
                    if text:
                        total_spans += 1
                        span_data = {
                            "block_idx": block_idx,
                            "line_idx": line_idx,
                            "span_idx": span_idx,
                            "text": text,
                            "font": span.get("font"),
                            "size": span.get("size"),
                            "color": span.get("color"),
                            "bbox": span.get("bbox"),
                        }
                        flags = span.get("flags")
                        if flags is not None:
                            span_data["flags"] = flags
                            span_data["is_bold"] = (flags & (1 << 0)) != 0
                            span_data["is_italic"] = (flags & (1 << 1)) != 0
                        spans_info.append(span_data)
    
    safe_print(f"\n=== 总Spans数量: {total_spans} ===")
    
    # 打印前15个spans
    safe_print(f"\n=== 前15个Spans详情 ===")
    for i, span in enumerate(spans_info[:15]):
        safe_print(f"\nSpan {i}:")
        safe_print(f"  Text: {span['text']}")
        safe_print(f"  Font: {span['font']}")
        safe_print(f"  Size: {span['size']:.2f}")
        safe_print(f"  BBox: {span['bbox']}")
        if "is_bold" in span:
            safe_print(f"  Bold: {span['is_bold']}")
        if "is_italic" in span:
            safe_print(f"  Italic: {span['is_italic']}")
        safe_print(f"  Color: {span['color']}")
    
    # 保存完整信息到文件
    output_file = "pdf_span_analysis.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "total_spans": total_spans,
            "spans": spans_info
        }, f, ensure_ascii=False, indent=2)
    safe_print(f"\n完整分析已保存到: {os.path.abspath(output_file)}")
    
    doc.close()

if __name__ == "__main__":
    analyze_pdf_structure()
