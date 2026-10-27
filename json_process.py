import json
import os
from datetime import datetime


def save_result(result: dict, source_path: str, out_dir: str, mail_info: dict = None, fields: dict = None) -> str:

    """ Save the extracted content of one attachment as JSON and return the path of the file. """

    mail_info = mail_info or {}
    name = os.path.splitext(os.path.basename(source_path))[0]
    text = result["text"]

    data = {
        "mail": {
            "sender": mail_info.get("sender"),
            "subject": mail_info.get("subject"),
            "date": mail_info.get("date"),
            "category": None,          # filled in when the whole mail is finished
            "reply_status": None,
        },
        "file": {
            "name": os.path.basename(source_path),
            "type": result["type"],
            "size_kb": round(os.path.getsize(source_path) / 1024, 1),
            "page_count": len(result["pages"]),
        },
        "processed_at": datetime.now().isoformat(timespec="seconds"),
        "word_count": len(text.split()),
        "char_count": len(text),
        "fields": fields or {},
        "tables": result["tables"],
        "pages": [{"number": p["number"], "method": p["method"], "text": p["text"]} for p in result["pages"]],
        "text": text,
    }

    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, name + ".json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return out_path


def update_mail(json_path: str, **values):

    """ Add the category and reply status to a saved JSON file once they are known. """

    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    data["mail"].update(values)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# It saves the text, tables, pages and fields of a file as JSON.
