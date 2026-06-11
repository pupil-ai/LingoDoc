def pixmap_to_export_image_bytes(pixmap) -> bytes:
    try:
        return pixmap.tobytes("jpeg", jpg_quality=82)
    except Exception:
        return pixmap.tobytes("png")


def write_optimized_pdf(doc) -> bytes:
    try:
        doc.subset_fonts()
    except Exception as e:
        print(f"[DEBUG] Failed to subset fonts: {str(e)}")

    return doc.write(deflate=True, garbage=4, clean=True)
