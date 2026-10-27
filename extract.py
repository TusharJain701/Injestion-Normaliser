"""
Turn one saved attachment into text, tables and pages.

PDF   each page is checked on its own:
        enough real text  -> read directly (no OCR) and look for tables
        little text       -> draw the page as a picture, clean it, OCR it
      so a PDF that is half digital and half scanned is handled page by page.
Image the picture is cleaned and read with OCR (multi-page TIFFs page by page).
"""

import os

import pymupdf
from PIL import Image, ImageSequence

import config
import digital_pdf_process
import image_process
import ocr_process
import scanned_pdf_process

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp")


class NoTextError(Exception):
    """The file opened fine but no text could be found in it (retrying will not help)."""


class ProtectedError(Exception):
    """The PDF needs a password."""


def _result(kind: str, pages: list) -> dict:
    text = "\n\n".join(p["text"] for p in pages if p["text"])
    if not text.strip():
        raise NoTextError("No text could be found in the file")
    tables = [{"page": p["number"], "rows": rows} for p in pages for rows in p["tables"]]
    return {"type": kind, "pages": pages, "tables": tables, "text": text}


def _extract_pdf(path: str) -> dict:
    min_chars = config.setting("min_digital_chars")
    dpi = config.setting("ocr_dpi")
    pages = []

    with pymupdf.open(path) as doc:
        if doc.needs_pass:
            raise ProtectedError("The PDF is password protected")

        for number, page in enumerate(doc, 1):
            text = page.get_text().strip()
            method, tables = "digital", []

            if len(text) >= min_chars or not page.get_images():
                tables = digital_pdf_process.read_tables(page)          # digital page: no OCR
            else:
                picture = image_process.preprocess_image(scanned_pdf_process.page_to_image(page, dpi))
                ocr_text = ocr_process.ocr_image(picture).strip()
                if len(ocr_text) > len(text):                            # keep whichever read more
                    text, method = ocr_text, "ocr"

            pages.append({"number": number, "method": method, "text": text, "tables": tables})

    methods = {p["method"] for p in pages}
    kind = "digital" if methods == {"digital"} else "scanned" if methods == {"ocr"} else "mixed"
    return _result(kind, pages)


def _extract_image(path: str) -> dict:
    pages = []
    with Image.open(path) as img:
        for number, frame in enumerate(ImageSequence.Iterator(img), 1):
            picture = image_process.preprocess_image(frame.copy())
            pages.append({"number": number, "method": "ocr", "text": ocr_process.ocr_image(picture).strip(), "tables": []})
    return _result("image", pages)


def extract_file(path: str) -> dict:

    """ Returns {"type", "pages", "tables", "text"}. Raises NoTextError, ProtectedError or another error. """

    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return _extract_pdf(path)
    if ext in IMAGE_EXTS:
        return _extract_image(path)
    raise ValueError("Unsupported file type: %s" % ext)
