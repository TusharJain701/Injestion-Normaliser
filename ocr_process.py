import pytesseract

import config


def ocr_image(img) -> str:

    """ Read the text of one (already cleaned) image with Tesseract. """

    cmd = config.setting("tesseract_cmd")
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd
    return pytesseract.image_to_string(img, lang=config.setting("ocr_language"))


def tesseract_version():

    """ Version text if Tesseract can be found, otherwise None. """

    cmd = config.setting("tesseract_cmd")
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd
    try:
        return str(pytesseract.get_tesseract_version())
    except Exception:
        return None


# It takes an image in and gives the extracted text back.
