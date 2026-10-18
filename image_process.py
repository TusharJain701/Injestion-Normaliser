from PIL import Image, ImageOps, ImageFilter
def preprocess_image(img: Image.Image) -> Image.Image:

    """ Fix rotation, flatten transparency, grayscale, boost contrast, upscale, sharpen. """

    # Step 1: Fixing Rotation
    img = ImageOps.exif_transpose(img)

    # Step 2: Removing Transparency and creatomg a plain white background
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, img)

    # Step 3: Making it Grayscale 
    img = img.convert("L")

    # Step 4: Boosting Contrast
    img = ImageOps.autocontrast(img)

    # Step 5: Enlarging small images
    if img.width < 1000:  # Tesseract likes ~300 DPI
        scale = 2 if img.width >= 500 else 3
        img = img.resize((img.width * scale, img.height * scale), Image.LANCZOS)

    # Step 6: Sharpen and returning 
    return img.filter(ImageFilter.SHARPEN)


# It takes an image in and gives an improved image back.