"""
End-to-end test with a fake Gmail: the Gmail calls are stubbed, everything else is real
(PDF reading, OCR, tables, rules, replies, database).   Run:  python -m unittest test_pipeline -v
Needs Tesseract for the scanned and image cases.
"""

import base64
import copy
import email
import io
import json
import os
import shutil
import tempfile
import unittest

import pymupdf
from PIL import Image, ImageDraw, ImageFont

import config
import main
import ocr_process
import store

INVOICE_LINES = ["INVOICE", "Invoice No. 2026-0412", "Bill to: Example Traders", "Date: 19 Oct 2026",
                 "Subtotal: 11,000.00", "Total due: Rs 12,400.00"]


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode()


# ---------------------------------------------------------------- sample files

def _font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.truetype("DejaVuSans.ttf", size)


def invoice_picture() -> Image.Image:
    img = Image.new("RGB", (1400, 700), "white")
    draw, font, y = ImageDraw.Draw(img), _font(44), 50
    for line in INVOICE_LINES:
        draw.text((60, y), line, fill="black", font=font)
        y += 72
    return img


def png_bytes(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def digital_pdf_with_table() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    y = 72
    for line in INVOICE_LINES[:4]:
        page.insert_text((72, y), line, fontsize=12)
        y += 20
    rows = [["Item", "Qty", "Price"], ["Paper", "10", "500.00"], ["Ink", "4", "1,500.00"], ["Toner", "2", "4,500.00"]]
    x0, y0 = 72, y + 10
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            rect = pymupdf.Rect(x0 + c * 110, y0 + r * 24, x0 + (c + 1) * 110, y0 + (r + 1) * 24)
            page.draw_rect(rect, color=(0, 0, 0), width=0.8)
            page.insert_text((rect.x0 + 6, rect.y1 - 8), cell, fontsize=11)
    y = y0 + len(rows) * 24 + 24
    for line in INVOICE_LINES[4:]:
        page.insert_text((72, y), line, fontsize=12)
        y += 20
    data = doc.tobytes()
    doc.close()
    return data


def scanned_pdf() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=300)
    page.insert_image(page.rect, stream=png_bytes(invoice_picture()))
    data = doc.tobytes()
    doc.close()
    return data


def mixed_pdf() -> bytes:
    doc = pymupdf.open()
    p1 = doc.new_page()
    for i, line in enumerate(INVOICE_LINES[:4]):
        p1.insert_text((72, 72 + i * 20), line, fontsize=12)
    p2 = doc.new_page(width=595, height=300)
    p2.insert_image(p2.rect, stream=png_bytes(invoice_picture()))
    data = doc.tobytes()
    doc.close()
    return data


def locked_pdf() -> bytes:
    doc = pymupdf.open(stream=digital_pdf_with_table(), filetype="pdf")
    data = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="owner")
    doc.close()
    return data


# ---------------------------------------------------------------- fake Gmail

class _Req:
    def __init__(self, fn):
        self.fn = fn

    def execute(self, num_retries=0):
        return self.fn()


class FakeGmail:
    def __init__(self, my_address="inbox@example.com"):
        self.my_address = my_address
        self.mails, self.blobs, self.sent = {}, {}, []
        self.counter = 0

    def add(self, sender, subject, body="", files=(), headers=None, sender_name=""):
        self.counter += 1
        msg_id = "m%d" % self.counter
        parts = [{"mimeType": "text/plain", "filename": "", "body": {"data": b64(body.encode()), "size": len(body)}}]
        for i, (name, data) in enumerate(files):
            att_id = "a%d_%d" % (self.counter, i)
            self.blobs[(msg_id, att_id)] = data
            parts.append({"mimeType": "application/octet-stream", "filename": name,
                          "body": {"attachmentId": att_id, "size": len(data)}})
        hdrs = [("From", ('"%s" <%s>' % (sender_name, sender)) if sender_name else sender),
                ("To", self.my_address), ("Subject", subject), ("Date", "Mon, 19 Oct 2026 10:30:00 +0530"),
                ("Message-ID", "<%s@test>" % msg_id)] + list((headers or {}).items())
        self.mails[msg_id] = {"id": msg_id, "threadId": "t" + msg_id, "labelIds": ["INBOX", "UNREAD"],
                              "payload": {"mimeType": "multipart/mixed", "parts": parts,
                                          "headers": [{"name": k, "value": v} for k, v in hdrs]}}
        return msg_id

    def users(self):
        return _Users(self)

    def unread(self):
        return [i for i, m in self.mails.items() if "UNREAD" in m["labelIds"]]


class _Users:
    def __init__(self, g):
        self.g = g

    def getProfile(self, userId):
        return _Req(lambda: {"emailAddress": self.g.my_address})

    def messages(self):
        return _Messages(self.g)


class _Messages:
    def __init__(self, g):
        self.g = g

    def list(self, userId, labelIds=None, q=None):
        return _Req(lambda: {"messages": [{"id": i} for i in reversed(self.g.unread())]})

    def list_next(self, request, response):
        return None

    def get(self, userId, id, format):
        return _Req(lambda: copy.deepcopy(self.g.mails[id]))

    def modify(self, userId, id, body):
        def run():
            for label in body.get("removeLabelIds", []):
                if label in self.g.mails[id]["labelIds"]:
                    self.g.mails[id]["labelIds"].remove(label)
            return {}
        return _Req(run)

    def send(self, userId, body):
        def run():
            msg = email.message_from_bytes(base64.urlsafe_b64decode(body["raw"]))
            self.g.sent.append({"to": msg["To"], "subject": msg["Subject"], "thread": body.get("threadId"),
                                "in_reply_to": msg["In-Reply-To"], "auto": msg["Auto-Submitted"],
                                "body": msg.get_payload(decode=True).decode()})
            return {"id": "sent%d" % len(self.g.sent)}
        return _Req(run)

    def attachments(self):
        return self

    def get_attachment(self):
        raise NotImplementedError


# Gmail's attachments().get has the same name as messages().get, so give it its own small class
class _Attachments:
    def __init__(self, g):
        self.g = g

    def get(self, userId, messageId, id):
        return _Req(lambda: {"data": b64(self.g.blobs[(messageId, id)])})


_Messages.attachments = lambda self: _Attachments(self.g)


# ---------------------------------------------------------------- the tests

class Pipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        config.load()
        s = config.get()["settings"]
        s["attachments_dir"] = os.path.join(self.tmp, "attachments")
        s["output_dir"] = os.path.join(self.tmp, "output")
        store.DB_PATH = os.path.join(self.tmp, "test.db")
        store.init_db()
        self.gmail = FakeGmail()
        main._failures.clear()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        config.load()

    # helpers
    def run_mail(self, dry_run=False):
        main.run_once(self.gmail, self.gmail.my_address, dry_run)

    def db_email(self, msg_id):
        return store._query("SELECT * FROM emails WHERE gmail_msg_id = ?", (msg_id,))[0]

    def json_files(self):
        out = config.setting("output_dir")
        return [os.path.join(out, f) for f in sorted(os.listdir(out))] if os.path.isdir(out) else []

    def load_json(self, path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def need_ocr(self):
        if not ocr_process.tesseract_version():
            self.skipTest("Tesseract is not installed")

    # --- documents
    def test_digital_pdf_tables_fields_and_reply(self):
        mid = self.gmail.add("john@example.com", "Invoice for October", "Invoice attached.",
                             [("invoice.pdf", digital_pdf_with_table())], sender_name="John Smith")
        self.run_mail()

        data = self.load_json(self.json_files()[0])
        self.assertEqual(data["file"]["type"], "digital")
        self.assertEqual([p["method"] for p in data["pages"]], ["digital"])      # no OCR was used
        self.assertEqual(data["tables"][0]["rows"][2], ["Ink", "4", "1,500.00"])
        self.assertEqual(data["fields"], {"invoice_no": "2026-0412", "invoice_total": 12400.0})
        self.assertEqual(data["mail"]["category"], "DOC_SUBMISSION")
        self.assertEqual(data["mail"]["reply_status"], "sent")

        self.assertEqual(len(self.gmail.sent), 1)
        reply = self.gmail.sent[0]
        self.assertEqual(reply["to"], "john@example.com")
        self.assertEqual(reply["thread"], "t" + mid)
        self.assertEqual(reply["in_reply_to"], "<%s@test>" % mid)
        self.assertEqual(reply["auto"], "auto-replied")
        self.assertIn("Hello John,", reply["body"])
        self.assertIn("Reference:", reply["body"])
        self.assertTrue(any(os.path.basename(f).endswith("invoice.json") for f in self.json_files()))
        self.assertEqual(self.gmail.unread(), [])
        row = self.db_email(mid)
        self.assertEqual((row["category"], row["reply_status"], row["flagged"]), ("DOC_SUBMISSION", "sent", 0))

    def test_scanned_pdf_is_read_with_ocr(self):
        self.need_ocr()
        self.gmail.add("a@example.com", "Scan", "", [("scan.pdf", scanned_pdf())])
        self.run_mail()
        data = self.load_json(self.json_files()[0])
        self.assertEqual(data["file"]["type"], "scanned")
        self.assertEqual(data["pages"][0]["method"], "ocr")
        self.assertEqual(data["fields"]["invoice_total"], 12400.0)

    def test_image_is_read_with_ocr(self):
        self.need_ocr()
        self.gmail.add("a@example.com", "Photo", "", [("photo.png", png_bytes(invoice_picture()))])
        self.run_mail()
        data = self.load_json(self.json_files()[0])
        self.assertEqual(data["file"]["type"], "image")
        self.assertEqual(data["fields"]["invoice_no"], "2026-0412")

    def test_mixed_pdf_reads_each_page_the_right_way(self):
        self.need_ocr()
        self.gmail.add("a@example.com", "Mixed", "", [("mixed.pdf", mixed_pdf())])
        self.run_mail()
        data = self.load_json(self.json_files()[0])
        self.assertEqual(data["file"]["type"], "mixed")
        self.assertEqual([p["method"] for p in data["pages"]], ["digital", "ocr"])

    # --- problems
    def test_locked_pdf(self):
        self.gmail.add("a@example.com", "Locked", "", [("locked.pdf", locked_pdf())])
        self.run_mail()
        self.assertEqual(self.json_files(), [])
        self.assertEqual(len(self.gmail.sent), 1)
        self.assertIn("password protected", self.gmail.sent[0]["body"])
        self.assertEqual(self.db_email("m1")["category"], "PROTECTED_OR_TOO_LARGE")

    def test_broken_pdf_fails_flags_and_alerts(self):
        config.get()["settings"]["alert_email"] = "admin@example.com"
        self.gmail.add("a@example.com", "Broken", "", [("broken.pdf", b"not a pdf at all" * 10)])
        self.run_mail()
        row = self.db_email("m1")
        self.assertEqual((row["category"], row["flagged"]), ("DOC_FAILED", 1))
        self.assertEqual(sorted(m["to"] for m in self.gmail.sent), ["a@example.com", "admin@example.com"])

    def test_unsupported_file(self):
        self.gmail.add("a@example.com", "Word", "", [("notes.docx", b"PK\x03\x04 fake")])
        self.run_mail()
        self.assertIn("notes.docx", self.gmail.sent[0]["body"])
        self.assertEqual(self.db_email("m1")["category"], "UNSUPPORTED_ATTACHMENT")

    # --- categories without documents
    def test_no_attachment_gets_a_reply(self):
        self.gmail.add("a@example.com", "Hello", "I will send it tomorrow.")
        self.run_mail()
        self.assertIn("no attachment", self.gmail.sent[0]["body"])

    def test_needs_human_is_flagged(self):
        self.gmail.add("a@example.com", "Problem", "I have a complaint about my order.")
        self.run_mail()
        row = self.db_email("m1")
        self.assertEqual((row["category"], row["flagged"]), ("NEEDS_HUMAN", 1))
        self.assertIn("person from our team", self.gmail.sent[0]["body"])

    def test_robot_mail_gets_no_reply_and_attachment_is_not_opened(self):
        self.gmail.add("noreply@bank.com", "Statement", "", [("statement.pdf", digital_pdf_with_table())])
        self.run_mail()
        self.assertEqual(self.gmail.sent, [])
        self.assertEqual(self.json_files(), [])
        self.assertEqual(self.db_email("m1")["category"], "AUTO_GENERATED")
        self.assertEqual(self.gmail.unread(), [])

    def test_same_file_sent_twice_is_a_duplicate(self):
        pdf = digital_pdf_with_table()
        self.gmail.add("a@example.com", "First", "", [("invoice.pdf", pdf)])
        self.gmail.add("b@example.com", "Second", "", [("invoice.pdf", pdf)])
        self.run_mail()
        self.assertEqual(self.db_email("m2")["category"], "DUPLICATE")
        self.assertEqual(len(self.gmail.sent), 1)

    # --- editable rules
    def test_rule_compares_mail_amount_with_document_amount(self):
        config.get()["rules"][1]["enabled"] = True
        self.gmail.add("a@example.com", "Invoice", "The total amount is 99,999 as agreed.",
                       [("invoice.pdf", digital_pdf_with_table())], sender_name="Asha")
        self.run_mail()
        body = self.gmail.sent[0]["body"]
        self.assertIn("99,999", body)
        self.assertIn("12,400", body)
        self.assertIn("does not match", body)
        self.assertNotIn("processed them successfully", body)         # the template was replaced
        row = self.db_email("m1")
        self.assertEqual(row["flagged"], 1)
        self.assertIn("Amount mismatch", row["flag_reason"])

    def test_rule_stays_quiet_when_amounts_match(self):
        config.get()["rules"][1]["enabled"] = True
        self.gmail.add("a@example.com", "Invoice", "The total amount is 12,400.",
                       [("invoice.pdf", digital_pdf_with_table())])
        self.run_mail()
        self.assertIn("processed them successfully", self.gmail.sent[0]["body"])
        self.assertEqual(self.db_email("m1")["flagged"], 0)

    def test_rule_adds_a_note_to_the_normal_reply(self):
        rule = config.get()["rules"][0]
        rule["enabled"] = True
        rule["when"] = ["invoice_total > 10000"]
        self.gmail.add("a@example.com", "Invoice", "", [("invoice.pdf", digital_pdf_with_table())])
        self.run_mail()
        body = self.gmail.sent[0]["body"]
        self.assertIn("processed them successfully", body)
        self.assertIn("needs approval first", body)
        self.assertEqual(self.db_email("m1")["flagged"], 1)

    def test_rule_can_silence_a_sender(self):
        config.get()["rules"][2]["enabled"] = True
        self.gmail.add("stranger@else.com", "Invoice", "", [("invoice.pdf", digital_pdf_with_table())])
        self.run_mail()
        self.assertEqual(self.gmail.sent, [])
        self.assertEqual(len(self.json_files()), 1)                   # the file is still saved
        self.assertEqual(self.db_email("m1")["flagged"], 1)

    def test_edited_template_is_used(self):
        config.get()["templates"]["NO_ATTACHMENT"]["body"] = "{greeting}\n\nPlease attach a file, {first_name}.\n\n{signature}"
        self.gmail.add("a@example.com", "Hello", "", sender_name="Ravi Kumar")
        self.run_mail()
        self.assertIn("Please attach a file, Ravi.", self.gmail.sent[0]["body"])

    # --- dry run
    def test_dry_run_sends_nothing_and_keeps_the_mail_unread(self):
        self.gmail.add("a@example.com", "Hello", "no file here")
        self.run_mail(dry_run=True)
        self.assertEqual(self.gmail.sent, [])
        self.assertEqual(self.gmail.unread(), ["m1"])


if __name__ == "__main__":
    unittest.main()
