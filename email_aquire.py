import base64
import os
import time

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


# gmail.modify lets us read mails and remove the UNREAD label (mark as read)
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
CREDENTIALS_FILE = "credentials.json"  # downloaded from Google Cloud Console
TOKEN_FILE = "token.json"              # created automatically after the first login
ALLOWED_EXTS = (".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp")


def get_service():

    """ Log in to Gmail with OAuth and return the Gmail API service. """

    # Step 1: Loading the saved login if there is one
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    # Step 2: Refreshing the login, or opening the browser to log in the first time
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        # Step 3: Saving the login so the browser is not needed next time
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    # Step 4: Building the Gmail API service
    return build("gmail", "v1", credentials=creds)


def _walk_parts(payload):

    """ Yield every part of a mail, including parts nested inside other parts. """

    yield payload
    for part in payload.get("parts", []):
        yield from _walk_parts(part)


def check_mail(save_dir="attachments") -> list:

    """
    Check the inbox once, download attachments from unread mails.
    Returns a list of (path, mail_info) for every saved file.
    """

    # Step 1: Creating the folder for attachments and connecting to Gmail
    os.makedirs(save_dir, exist_ok=True)
    service = get_service()
    saved_files = []

    # Step 2: Asking Gmail for unread inbox mails that have attachments (all pages)
    messages = []
    request = service.users().messages().list(
        userId="me", labelIds=["INBOX"], q="is:unread has:attachment"
    )
    while request is not None:
        response = request.execute()
        messages.extend(response.get("messages", []))
        request = service.users().messages().list_next(request, response)

    # Step 3: Reading each unread mail in full
    for item in messages:
        msg_id = item["id"]
        msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()

        # Step 4: Getting sender, subject and date from the mail headers
        headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
        mail_info = {
            "sender": headers.get("from"),
            "subject": headers.get("subject"),
            "date": headers.get("date"),
        }

        # Step 5: Going through the parts of the mail to find attachments
        for part in _walk_parts(msg["payload"]):
            filename = os.path.basename(part.get("filename", ""))
            if not filename or not filename.lower().endswith(ALLOWED_EXTS):
                continue

            # Step 6: Getting the file data (big files are fetched separately by attachment id)
            body = part.get("body", {})
            if "attachmentId" in body:
                att = service.users().messages().attachments().get(
                    userId="me", messageId=msg_id, id=body["attachmentId"]
                ).execute()
                data = att["data"]
            else:
                data = body.get("data")
            if not data:
                continue

            # Step 7: Saving the file, with the mail id in the name to avoid overwriting
            path = os.path.join(save_dir, f"{msg_id}_{filename}")
            with open(path, "wb") as f:
                f.write(base64.urlsafe_b64decode(data))
            saved_files.append((path, mail_info))

        # Step 8: Marking the mail as read (the API does not do this by itself)
        service.users().messages().modify(
            userId="me", id=msg_id, body={"removeLabelIds": ["UNREAD"]}
        ).execute()

    # Step 9: Returning the saved files with their mail details
    return saved_files


def watch_mail(on_file, save_dir="attachments", interval=30):

    """ Keep checking the inbox every `interval` seconds and call on_file(path, mail_info) for each new attachment. """

    print("Watching inbox... (press Ctrl+C to stop)")

    # Step 1: Checking the inbox again and again
    while True:
        for path, mail_info in check_mail(save_dir):
            print(f"New file: {path}")

            # Step 2: Handing each new file and its mail details to the function given by the caller
            on_file(path, mail_info)

        # Step 3: Waiting before the next check
        time.sleep(interval)


# check_mail() checks once and returns (path, mail_info) pairs, watch_mail() keeps checking.