import os
import email_aquire
import digital_pdf_process
import scanned_pdf_process
import image_process
import ocr_process
import json_process
import pdf_type


OUTPUT_DIR = "output"


def process_file(path: str, mail_info: dict = None):

    """ Take one downloaded file, get its text and save it as JSON. """

    # Step 1: Checking if the file is a PDF or an image
    ext = os.path.splitext(path)[1].lower()

    if ext == ".pdf":

        # Step 2: Checking the type of the PDF
        pdftype = pdf_type.check_pdf_type(path)

        if pdftype == "digital":
            # Step 3: Digital PDF, reading the text directly
            print("Pdf is Digital")
            text = digital_pdf_process.read_digital_pdf(path)

        else:
            # Step 4: Scanned or mixed PDF, turning pages into images, cleaning them and running OCR
            print("Pdf is Scanned")
            images = scanned_pdf_process.pdf_to_images(path)
            processed_images = [image_process.preprocess_image(img) for img in images]
            text = ocr_process.scanned_to_text(processed_images)

    else:
        # Step 5: Image file, OCR does the cleaning itself
        print("File is an Image")
        pdftype = "image"
        text = ocr_process.scanned_to_text(path)

    # Step 6: Saving the text and the mail details as a JSON file
    out_path = json_process.text_to_json(text, path, pdftype, OUTPUT_DIR, mail_info)
    print(f"Saved: {out_path}")


def main():

    # Step 7: Watching the inbox and processing every new attachment
    email_aquire.watch_mail(on_file=process_file, save_dir="attachments", interval=30)


if __name__ == "__main__":
    main()


# It watches Gmail, reads every new PDF or image and saves its text as JSON.