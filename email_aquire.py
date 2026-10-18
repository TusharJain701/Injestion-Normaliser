import imaplib
import email
import os
import time
from email.header import decode_header
from dotenv import load_dotenv


# Loading EMAIL_ADDRESS and EMAIL_APP_PASSWORD from the .env file
load_dotenv()

IMAP_SERVER = "imap.gmail.com"
IMAP_PORT = 993
ALLOWED_EXTS = (".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp")


def check_mail(save_dir="attachments") -> list:

    """ Check the inbox once, download attachments from unread mails and return their paths. """

    # Step 1: Creating the folder for attachments
    os.makedirs(save_dir, exist_ok=True)
    saved_files = []

    # Step 2: Logging in to Gmail and opening the inbox
    mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
    mail.login(os.getenv("EMAIL_ADDRESS"), os.getenv("EMAIL_APP_PASSWORD"))
    mail.select("INBOX")

    # Step 3: Searching for unread mails
    status, data = mail.search(None, "UNSEEN")
    mail_ids = data[0].split()

    # Step 4: Reading each unread mail (this also marks it as read)
    for mail_id in mail_ids:
        status, msg_data = mail.fetch(mail_id, "(RFC822)")
        msg = email.message_from_bytes(msg_data[0][1])

        # Step 5: Going through the parts of the mail to find attachments
        for part in msg.walk():
            filename = part.get_filename()
            if not filename:
                continue

            # Step 6: Decoding the file name (it can be encoded)
            raw, enc = decode_header(filename)[0]
            if isinstance(raw, bytes):
                filename = raw.decode(enc or "utf-8", errors="ignore")

            # Step 7: Saving only PDFs and images, with the mail id in the name to avoid overwriting
            if filename.lower().endswith(ALLOWED_EXTS):
                path = os.path.join(save_dir, f"{mail_id.decode()}_{filename}")
                with open(path, "wb") as f:
                    f.write(part.get_payload(decode=True))
                saved_files.append(path)

    # Step 8: Logging out and returning the saved file paths
    mail.logout()
    return saved_files


def watch_mail(on_file, save_dir="attachments", interval=30):

    """ Keep checking the inbox every `interval` seconds and call on_file(path) for each new attachment. """

    print("Watching inbox... (press Ctrl+C to stop)")

    # Step 1: Checking the inbox again and again
    while True:
        for path in check_mail(save_dir):
            print(f"New file: {path}")

            # Step 2: Handing each new file to the function given by the caller
            on_file(path)

        # Step 3: Waiting before the next check
        time.sleep(interval)


# check_mail() checks once and returns the saved files, watch_mail() keeps checking.