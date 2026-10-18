import email_aquire
import pdf_process
import image_process
from PIL import Image

img = Image.open(r"D:\Group_project\Injestion-Normaliser\test_image.png")
image_processed = image_process.preprocess_image(img)
image_processed.save("Output.png")