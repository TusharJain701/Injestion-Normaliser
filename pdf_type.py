import pymupdf

def check_pdf_type(pdf_path: str, min_chars: int = 50) -> str:

    """
    Returns "digital", "scanned", or "mixed".
    A page counts as digital if it has at least `min_chars` characters of real text.
    """

    # Step 1: Opening the PDF and setting up the counters
    doc = pymupdf.open(pdf_path)
    digital_pages = 0
    scanned_pages = 0

    # Step 2: Checking each page for text and images
    for page in doc:
        text = page.get_text().strip()
        has_images = len(page.get_images()) > 0

        # Step 3: Enough text means digital page, little text with images means scanned page
        if len(text) >= min_chars:
            digital_pages += 1
        elif has_images:
            scanned_pages += 1

    # Step 4: Closing the PDF
    doc.close()

    # Step 5: Deciding the final type from the page counts
    if digital_pages > 0 and scanned_pages == 0:
        return "digital"
    if scanned_pages > 0 and digital_pages == 0:
        return "scanned"
    return "mixed"


# It takes a PDF path in and tells if it is digital, scanned or mixed.