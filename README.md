# Ingestion-Normaliser

Watches a Gmail inbox, downloads PDF and image attachments from new mails, extracts their text and saves it as JSON.

## How it works

1. `email_aquire.py` checks Gmail (IMAP) for unread mails and downloads PDF/image attachments.
2. `pdf_type.py` checks if a PDF is digital, scanned or mixed.
3. Digital PDFs: `digital_pdf_process.py` reads the text directly.
4. Scanned PDFs and images: `scanned_pdf_process.py` turns pages into images, `image_process.py` cleans them, `ocr_process.py` runs OCR.
5. `json_process.py` saves the text as a JSON file in the `output` folder.
6. `main.py` ties everything together.

## Setup

1. Install Python packages:

   ```
   pip install -r requirements.txt
   ```

2. Install [Tesseract OCR](https://github.com/tesseract-ocr/tesseract)

3. Set up Gmail:
   - Turn on 2-Step Verification in your Google Account.
   - Create an app password: Google Account → Security → 2-Step Verification → App passwords.
   - Make sure IMAP is enabled in Gmail settings.

4. Create a `.env` file next to `main.py`:

   ```
   EMAIL_ADDRESS=yourid@gmail.com
   EMAIL_APP_PASSWORD=your16characterpassword
   ```

## Authentication (no API keys)

This project does not use any API keys. It connects to Gmail with the standard email protocol, IMAP, and the app password acts as the login.

1. `email_aquire.py` connects to `imap.gmail.com` and logs in with the address and app password from `.env`.
2. Every 30 seconds it asks Gmail for unread mails and downloads their PDF and image attachments.
3. Text extraction is done locally. PyMuPDF reads digital PDFs, and Tesseract (installed on the computer) does the OCR. Nothing is sent to any outside service.
4. The result is saved as a JSON file in the `output` folder.

The alternative is the Gmail API, which needs a Google Cloud project, OAuth setup and API credentials. IMAP with an app password is simpler for a demo.

## Usage

Send a mail with a PDF or image attached to the Gmail address. Within 30 seconds the extracted text is saved as `output/<file name>.json`.

Only unread mails are processed, and they are marked as read.

## Output format

```json
{
  "mail": {
    "sender": "john@example.com",
    "subject": "Invoice for October",
    "date": "Mon, 19 Oct 2026 10:30:00 +0530"
  },
  "file": {
    "name": "invoice.pdf",
    "type": "digital",
    "size_kb": 84.2
  },
  "processed_at": "2026-10-19T10:31:05",
  "word_count": 120,
  "char_count": 780,
  "text": "extracted text here..."
}
```

`file.type` is `digital`, `scanned`, `mixed` or `image`.

## Project files

| File | Purpose |
| --- | --- |
| `main.py` | Runs the whole pipeline |
| `email_aquire.py` | Downloads attachments from Gmail |
| `pdf_type.py` | Detects digital, scanned or mixed PDFs |
| `digital_pdf_process.py` | Text extraction from digital PDFs |
| `scanned_pdf_process.py` | Converts PDF pages to images |
| `image_process.py` | Cleans images for OCR |
| `ocr_process.py` | OCR with Tesseract |
| `json_process.py` | Saves text as JSON |
