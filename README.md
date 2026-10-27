# Ingestion Normaliser

Watches a Gmail inbox. For every new mail it:

1. reads the mail and puts it in a **category**,
2. saves each **attachment as JSON** (text, tables, fields). Digital PDFs are read directly, OCR is used only for pages that are pictures,
3. **replies** using texts and rules that you edit in one file, `config.yaml`.

Everything runs on your computer. Mail content is sent to no outside service except Gmail itself.

## Setup

1. Install Python 3.10 or newer, then `pip install -r requirements.txt`
2. Install [Tesseract OCR](https://github.com/tesseract-ocr/tesseract). On Windows, if it is not found, set `tesseract_cmd` in `config.yaml`
   (for example `C:\Program Files\Tesseract-OCR\tesseract.exe`).
3. Gmail API login (once):
   - Google Cloud Console: create a project, enable the **Gmail API**.
   - OAuth consent screen: type **External**, add your Gmail address as a **test user**.
   - Credentials: create an **OAuth client ID** of type **Desktop app**, download the JSON and save it as `credentials.json` next to `main.py`.
4. First run: `python main.py --dry-run --once`. A browser opens for the Google login (one time only; `token.json` remembers it).

## Run

```
python main.py             watch the inbox, check every 30 seconds
python main.py --once      check once and stop
python main.py --dry-run   show what would happen. Nothing is sent, nothing is marked as read,
                           and a dry run keeps its own files and database
```

Try `--dry-run --once` first. It prints the category and the exact reply for every unread mail, without touching anything.

## Categories

The first matching line wins.

| Category | When | Reply |
| --- | --- | --- |
| `AUTO_GENERATED` | no-reply address, bounce, newsletter, out-of-office | never |
| `SUSPICIOUS` | SPF/DKIM/DMARC failed, blocked sender, dangerous file type (.exe, .js, ...) | never, attachments not opened |
| `DUPLICATE` | mail or file already processed | never |
| `NEEDS_HUMAN` | one of `needs_human_words`, or a question with no usable file | holding reply, mail is flagged |
| `NO_ATTACHMENT` | no attachment | asks for one |
| `PROTECTED_OR_TOO_LARGE` | password-protected PDF or file over `max_file_mb` | asks for another copy |
| `DOC_FAILED` | a file could not be read | asks to resend, mail is flagged |
| `UNSUPPORTED_ATTACHMENT` | not a PDF or image | lists accepted types |
| `DOC_SUBMISSION` | at least one file processed | confirmation with reference |

If a mail has several files, a problem with any file decides the category, and the reply also lists the files that did work.

## Editing replies: `config.yaml`

Save the file and the running program uses the change on its next inbox check. A mistake is reported with the exact line of the problem,
and the previous version stays in use.

**Change a reply text**: edit it under `templates:`. Names in `{ }` are filled in (`{greeting}`, `{files}`, `{references}`, `{problems}`, `{signature}`, ...).
The full list is in the file.

**Compare or react to something**: add a rule under `rules:`. Three examples are in the file, switched off.

```yaml
rules:
  - name: Amount in the mail does not match the document
    when:
      - invoice_total exists
      - claimed_total exists
      - invoice_total != claimed_total       # compares two values
    mode: replace                            # send this instead of the normal reply
    reply: |
      {greeting}

      The amount in your mail ({claimed_total}) does not match the total in {files} ({invoice_total}).
      Please check it and send the correct file.

      {signature}
    flag: Amount mismatch                    # also marks the mail for a person
```

- `when` lines: `<name> <test> <value>`. Tests: `==  !=  >  >=  <  <=  contains  not contains  matches  not matches  in  not in  exists  missing`.
  All lines must be true. For "or", write two rules.
- Names: your own **fields** plus `category sender subject body text filename file_count ok_count`.
- A rule can: add text to the normal reply (`mode: append`, shown where `{rule_notes}` stands), replace the reply (`mode: replace`),
  stay silent (`no_reply: true`), `flag` the mail, or change the `category`.
- If a value a line needs was not found, that line is false. Use `missing` to test for it.

**Fields** are values found with a pattern (regular expression) in documents or in the mail. They are saved in each JSON file and can be used in rules and templates.
The patterns shipped in the file (`invoice_no`, `invoice_total`, `claimed_total`) are examples: **adjust them to your own documents**.

## Output

One JSON file per attachment in `output/`:

```json
{
  "mail": {"sender": "...", "subject": "...", "date": "...", "category": "DOC_SUBMISSION", "reply_status": "sent"},
  "file": {"name": "invoice.pdf", "type": "digital", "size_kb": 84.2, "page_count": 1},
  "processed_at": "2026-10-20T10:31:05",
  "word_count": 30,
  "char_count": 210,
  "fields": {"invoice_no": "2026-0412", "invoice_total": 12400.0},
  "tables": [{"page": 1, "rows": [["Item", "Qty", "Price"], ["Ink", "4", "1,500.00"]]}],
  "pages": [{"number": 1, "method": "digital", "text": "..."}],
  "text": "..."
}
```

`file.type` is `digital`, `scanned`, `mixed` or `image`. Each page's `method` is `digital` or `ocr`.
The original files are kept in `attachments/`. Mails, documents, reply status and flags are in the SQLite database `ingestion.db`
(table `emails` has `category`, `reply_status`, `flagged`, `flag_reason`).

## Files

| File | Job |
| --- | --- |
| `main.py` | the program |
| `config.yaml` | limits, reply texts, fields, rules (the file you edit) |
| `config.py` | reads and checks `config.yaml` |
| `email_aquire.py` | Gmail API: login, fetch, download, mark as read |
| `mail_parser.py` | turns a Gmail message into a simple dictionary |
| `classifier.py` | the categories |
| `extract.py` | file to text, tables and pages (decides per page: direct or OCR) |
| `digital_pdf_process.py`, `scanned_pdf_process.py`, `image_process.py`, `ocr_process.py` | tables, page to picture, picture cleanup, Tesseract |
| `rules.py` | fields and rules |
| `replies.py` | reply text, reply limits, sending |
| `json_process.py` | writes the JSON files |
| `store.py` | SQLite database |

## Tests

```
python -m unittest test_rules test_pipeline -v      rules, config, and a full run against a fake Gmail (real PDFs and OCR)
python evaluate.py                                  50 sample mails with their correct category and reply
```

## Limits to know about

- **Gmail was only tested through a stand-in.** The login, fetch, download, mark-as-read and send calls are written to the Gmail API but have not been run against a real mailbox. Start with `--dry-run --once`.
- **Tables are found in digital PDFs only.** In scanned pages and images the table text is read by OCR as normal lines.
- **Replies are plain text** from your templates. No AI model writes them.
- **Keyword matching is simple.** "Please ignore my earlier complaint" still goes to a person (the safe direction).
- **Field patterns need tuning** for your own invoices or forms.
- **Other OCR languages** need the Tesseract language pack installed, then `ocr_language: eng+hin` (for example).
- **Mails are polled**, not pushed: a mail is handled within `poll_interval_seconds`.
- The login uses the Gmail permission `gmail.modify` (read, mark as read, send). Keep `credentials.json` and `token.json` private.
