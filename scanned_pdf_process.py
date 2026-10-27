from PIL import Image


def page_to_image(page, dpi: int = 300) -> Image.Image:

    """ Draw one PDF page as a picture so that OCR can read it. """

    pix = page.get_pixmap(dpi=dpi)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


# It takes a PDF page in and gives a PIL image back.
