import pymupdf

def read_digital_pdf(pdf_path: str) -> str:
    
    """Extract all text from a digital PDF."""

    doc = pymupdf.open(pdf_path)
    all_text = []

    for page in doc:
        all_text.append(page.get_text())

    doc.close()
    return "\n".join(all_text)