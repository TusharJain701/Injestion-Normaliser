import os
import pytesseract
from PIL import Image

import image_process


IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp")


def scanned_to_text(source, lang="eng"):

    """
    Turn scanned content into text.

    source can be:
      - path to an image file
      - a PIL Image
      - a list of PIL Images (already processed)

    Returns all text joined page by page.
    """

    # Step 1: If source is a file path, check it is an image and open it
    if isinstance(source, str):

        ext = os.path.splitext(source)[1].lower()

        if ext in IMAGE_EXTS:
            images = [Image.open(source)]
        else:
            raise ValueError(f"Unsupported file type: {ext}")


        # Step 2: Preprocess the opened image (only for paths, not for PIL inputs)
        images = [image_process.preprocess_image(img) for img in images]


    # Step 3: If source is a single PIL image, put it in a list
    elif isinstance(source, Image.Image):
        images = [source]


    # Step 4: Otherwise assume it is already a list of PIL images
    else:
        images = list(source)


    # Step 5: Run OCR on each image to get one text block per page
    pages = [pytesseract.image_to_string(img, lang=lang) for img in images]

    # Step 6: Join all pages into one string and return it
    return "\n".join(pages)


# It takes an image (or images) in and gives the extracted text back.