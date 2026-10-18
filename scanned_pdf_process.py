import pymupdf
import os
from PIL import Image

def pdf_to_images(pdf_path, dpi=300, out_dir=None):

    """ Convert each PDF page to a PIL image. Optionally save them as PNGs in out_dir. """

    # Step 1: Creating the output folder if one is given
    if out_dir: os.makedirs(out_dir, exist_ok=True)
    images = []

    # Step 2: Opening the PDF
    with pymupdf.open(pdf_path) as doc:
        for i, page in enumerate(doc):

            # Step 3: Rendering the page as a picture at the given DPI
            pix = page.get_pixmap(dpi=dpi)

            # Step 4: Converting the picture into a PIL image
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

            # Step 5: Saving the page as PNG if a folder is given
            if out_dir: img.save(f"{out_dir}/page_{i+1}.png")
            images.append(img)

    # Step 6: Returning the list of page images
    return images


# It takes a PDF path in and gives a list of page images back.