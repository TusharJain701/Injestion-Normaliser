import pymupdf

def check_pdf_type(pdf_path: str, min_chars: int = 50) -> str:
    
    """
    Returns "digital", "scanned", or "mixed".
    A page counts as digital if it has at least `min_chars` characters of real text.
    """

    doc = pymupdf.open(pdf_path)
    digital_pages = 0
    scanned_pages = 0

    for page in doc:
        text = page.get_text().strip()
        has_images = len(page.get_images()) > 0

        if len(text) >= min_chars:
            digital_pages += 1
        elif has_images:
            scanned_pages += 1

    doc.close()

    if digital_pages > 0 and scanned_pages == 0:
        return "digital"
    if scanned_pages > 0 and digital_pages == 0:
        return "scanned"
    return "mixed"