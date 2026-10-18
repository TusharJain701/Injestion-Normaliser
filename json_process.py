import json
import os


def text_to_json(text: str, source_path: str, pdf_type: str, out_dir: str = ".") -> str:

    """ Convert extracted text into a JSON file and return the path of the saved file. """

    # Step 1: Getting the file name without folder and extension
    name = os.path.splitext(os.path.basename(source_path))[0]

    # Step 2: Putting the text and its details into a dictionary
    data = {
        "file": name,
        "type": pdf_type,
        "text": text
    }

    # Step 3: Creating the output folder if it doesn't exist
    os.makedirs(out_dir, exist_ok=True)

    # Step 4: Saving the dictionary as a JSON file
    out_path = os.path.join(out_dir, f"{name}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # Step 5: Returning the path of the saved file
    return out_path


# It takes the extracted text in and saves it as a JSON file.