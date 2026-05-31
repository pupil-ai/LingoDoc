import fitz

doc = fitz.open("test_frontend.pdf")
print(f"Pages: {len(doc)}")

for page_num in range(len(doc)):
    page = doc[page_num]
    text = page.get_text()
    has_chinese = any('\u4e00' <= c <= '\u9fff' for c in text)
    print(f"Page {page_num+1}: Has Chinese = {has_chinese}")
    
    page_width = page.rect.width / 2
    blocks = page.get_text("blocks")
    right_count = 0
    for block in blocks:
        if len(block) >= 5:
            x0 = block[0]
            if x0 > page_width:
                right_count += 1
    print(f"  Right side blocks: {right_count}")

doc.close()