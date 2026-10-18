import pymupdf
import os
from PIL import Image
import image_process

def pdf_to_images(pdf_path, dpi=300, out_dir=None):

    """Convert each PDF page to a PIL image. Optionally save them as PNGs in out_dir."""

    if out_dir: os.makedirs(out_dir, exist_ok=True)
    images = []

    with pymupdf.open(pdf_path) as doc:
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=dpi)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            if out_dir: img.save(f"{out_dir}/page_{i+1}.png")
            images.append(img)

    return images