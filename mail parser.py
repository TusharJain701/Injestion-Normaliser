import base64
import os
import re
from email.utils import parseaddr


def b64decode(data: str) -> bytes:

    """ Decode Gmail's base64url data (adds the padding if it is missing). """

    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def walk_parts(payload):

    """ Yield every part of a mail, including parts nested inside other parts. """

    yield payload
    for part in payload.get("parts", []):
        yield from walk_parts(part)


def _part_headers(part) -> dict:
    return {h["name"].lower(): h["value"] for h in part.get("headers", [])}


def _is_inline_image(part) -> bool:

    """ Logos and pictures inside the mail body are not real attachments. """

    h = _part_headers(part)
    return h.get("content-disposition", "").strip().lower().startswith("inline") and "content-id" in h


def parse_message(msg: dict) -> dict:

    """ Turn a Gmail API message (format=full) into a simple dictionary. """

    payload = msg["payload"]

    # Step 1: Headers (repeated headers are joined, so Authentication-Results is not lost)
    headers = {}
    for h in payload.get("headers", []):
        name = h["name"].lower()
        headers[name] = headers[name] + " | " + h["value"] if name in headers else h["value"]

    sender_name, sender_email = parseaddr(headers.get("from", ""))
    _, reply_to_email = parseaddr(headers.get("reply-to", ""))

    # Step 2: Body text and attachment details (the files are not downloaded here)
    text_parts, html_parts, attachments = [], [], []
    for part in walk_parts(payload):
        body = part.get("body", {})
        filename = part.get("filename", "")

        if filename:
            if _is_inline_image(part):
                continue
            attachments.append({
                "filename": os.path.basename(filename),
                "size": body.get("size", 0),
                "attachment_id": body.get("attachmentId"),
                "data": body.get("data"),
            })
        elif part.get("mimeType") == "text/plain" and body.get("data"):
            text_parts.append(b64decode(body["data"]).decode("utf-8", errors="replace"))
        elif part.get("mimeType") == "text/html" and body.get("data"):
            html_parts.append(b64decode(body["data"]).decode("utf-8", errors="replace"))

    text = "\n".join(text_parts)
    if not text and html_parts:
        text = re.sub(r"<[^>]+>", " ", "\n".join(html_parts))

    return {
        "id": msg["id"],
        "thread_id": msg.get("threadId"),
        "sender_name": sender_name,
        "sender_email": sender_email.lower(),
        "reply_to_email": reply_to_email.lower(),
        "subject": headers.get("subject", ""),
        "date": headers.get("date"),
        "message_id": headers.get("message-id", ""),
        "references": headers.get("references", ""),
        "headers": headers,
        "body": text,
        "attachments": attachments,
    }