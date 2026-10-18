import os
import email_aquire
import digital_pdf_process
import scanned_pdf_process
import image_process
import pdf_type
from PIL import Image


pdf_path = r"pdf path"

pdftype = pdf_type.check_pdf_type(pdf_path)

if pdftype == "digital":
    print("Pdf is Digital")
    pdf_process = digital_pdf_process.read_digital_pdf(pdf_path)

    name = os.path.splitext(os.path.basename(pdf_path))[0]
    with open(f"{name}.txt", "w", encoding="utf-8") as f:
        f.write(pdf_process)

else:
    print("Pdf is scanend")
    pdf_process = scanned_pdf_process.pdf_to_images(pdf_path)
    processed_images = []
    for i, img in enumerate(pdf_process):
        processed = image_process.preprocess_image(img)
        processed.save(f"page_{i+1}_processed.png")
        processed_images.append(processed)