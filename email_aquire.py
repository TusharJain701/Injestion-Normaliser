import os
import re

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

import mail_parser

# gmail.modify lets us read mails, mark them as read and send replies
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_FILE = os.path.join(BASE_DIR, "credentials.json")   # downloaded from Google Cloud Console
TOKEN_FILE = os.path.join(BASE_DIR, "token.json")               # created after the first login


def get_service():

    """ Log in to Gmail with OAuth and return the Gmail API service. """

    # Step 1: Loading the saved login if there is one
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    # Step 2: Refreshing the login, or opening the browser to log in the first time
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                creds = None                      # the saved login is no longer valid, log in again
        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        # Step 3: Saving the login so the browser is not needed next time
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def fetch_unread(service):

    """ Yield every unread inbox mail as a simple dictionary (oldest first). Attachments are not downloaded yet. """

    ids = []
    request = service.users().messages().list(userId="me", labelIds=["INBOX"], q="is:unread")
    while request is not None:
        response = request.execute(num_retries=3)
        ids += [m["id"] for m in response.get("messages", [])]
        request = service.users().messages().list_next(request, response)

    for msg_id in reversed(ids):
        try:
            msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute(num_retries=3)
        except Exception as e:
            print("Could not read mail %s: %s" % (msg_id, e))
            continue
        yield mail_parser.parse_message(msg)


def download_attachment(service, mail: dict, att: dict, save_dir: str) -> str:

    """ Save one attachment and return its path. """

    if att.get("attachment_id"):
        data = service.users().messages().attachments().get(
            userId="me", messageId=mail["id"], id=att["attachment_id"]
        ).execute(num_retries=3)["data"]
    else:
        data = att.get("data")
    if not data:
        raise ValueError("the attachment has no data")

    os.makedirs(save_dir, exist_ok=True)
    safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", att["filename"]).strip() or "file"
    path = os.path.join(save_dir, "%s_%s" % (mail["id"], safe_name))

    base, ext = os.path.splitext(path)       # two attachments with the same name in one mail
    counter = 2
    while os.path.exists(path):
        path = "%s_%d%s" % (base, counter, ext)
        counter += 1

    with open(path, "wb") as f:
        f.write(mail_parser.b64decode(data))
    return path


def mark_read(service, msg_id: str):

    """ The API does not mark a mail as read by itself, so we remove the UNREAD label. """

    service.users().messages().modify(userId="me", id=msg_id, body={"removeLabelIds": ["UNREAD"]}).execute(num_retries=3)
