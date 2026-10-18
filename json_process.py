import json
import os
from datetime import datetime


def text_to_json(text: str, source_path: str, pdf_type: str, out_dir: str = ".", mail_info: dict = None) -> str:

    """ Convert extracted text and mail details into a JSON file and return the path of the saved file. """

    # Step 1: Getting the file name without folder and extension
    name = os.path.splitext(os.path.basename(source_path))[0]

    # Step 2: Using an empty dictionary if no mail details are given
    mail_info = mail_info or {}

    # Step 3: Putting the mail details, file details and text into a dictionary
    data = {
        "mail": {
            "sender": mail_info.get("sender"),
            "subject": mail_info.get("subject"),
            "date": mail_info.get("date")
        },
        "file": {
            "name": os.path.basename(source_path),
            "type": pdf_type,
            "size_kb": round(os.path.getsize(source_path) / 1024, 1)
        },
        "processed_at": datetime.now().isoformat(timespec="seconds"),
        "word_count": len(text.split()),
        "char_count": len(text),
        "text": text
    }

    # Step 4: Creating the output folder if it doesn't exist
    os.makedirs(out_dir, exist_ok=True)

    # Step 5: Saving the dictionary as a JSON file
    out_path = os.path.join(out_dir, f"{name}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # Step 6: Returning the path of the saved file
    return out_path


# It takes the extracted text and mail details in and saves them as a JSON file.
