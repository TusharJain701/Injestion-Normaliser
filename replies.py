import base64
from email.message import EmailMessage

import classifier
import store


MAX_REPLIES_PER_DAY = 5
ALLOWED_SENDERS = []   # empty = reply to everyone; or e.g. ["@mycompany.com", "boss@gmail.com"]

PROBLEM_REASONS = {
    "unsupported": "not a supported file type",
    "too_large": "larger than %d MB" % classifier.MAX_FILE_MB,
    "protected": "password protected",
    "failed": "could not be read",
}


def get_my_address(service) -> str:

    """ Our own Gmail address, so we never reply to ourselves. """

    return service.users().getProfile(userId="me").execute()["emailAddress"].lower()


def recipient(mail: dict) -> str:

    """ Reply-To if the mail has one, otherwise From. """

    return mail["reply_to_email"] or mail["sender_email"]


def greeting(mail: dict) -> str:
    parts = mail["sender_name"].strip().strip('"').split()
    return "Hello %s," % parts[0] if parts else "Hello,"


def reply_subject(mail: dict) -> str:
    subject = mail["subject"].strip() or "(no subject)"
    return subject if subject.lower().startswith("re:") else "Re: " + subject


def make_context(outcomes: list, email_id: int) -> dict:

    """ Collect what the reply needs: processed files, problem files and the mail id. """

    ok = [(o["file"], o["doc_id"]) for o in outcomes if o["outcome"] == "ok"]
    problems = [(o["file"], PROBLEM_REASONS[o["outcome"]]) for o in outcomes if o["outcome"] in PROBLEM_REASONS]
    return {"ok": ok, "problems": problems, "email_id": email_id}


def can_reply(mail: dict, category: str, my_address: str):

    """ Apply the reply rules. Returns (True, "ok") or (False, reason). """

    if category in classifier.NO_REPLY_CATEGORIES:
        return False, "this category never gets a reply"

    to = recipient(mail)
    if not to:
        return False, "no address to reply to"

    mine = my_address.lower()
    if to == mine or mail["sender_email"] == mine:
        return False, "own address"

    if store.is_blocked(to) or store.is_blocked(mail["sender_email"]):
        return False, "sender is blocked"

    if ALLOWED_SENDERS and not any(to == a or to.endswith(a) for a in ALLOWED_SENDERS):
        return False, "sender is not on the allowlist"

    if store.replies_last_day(mail["sender_email"]) >= MAX_REPLIES_PER_DAY:
        return False, "already %d replies to this sender today" % MAX_REPLIES_PER_DAY

    if store.replied_recently(mail["sender_email"], category):
        return False, "same category was answered in the last hour"

    return True, "ok"


def build_reply(category: str, mail: dict, ctx: dict):

    """ Return the reply text for a category, or None if the category has no template. """

    hello = greeting(mail)
    files = ", ".join(name for name, _ in ctx["ok"])
    refs = ", ".join(str(i) for _, i in ctx["ok"])
    problems = "\n".join("  - %s: %s" % (name, why) for name, why in ctx["problems"])

    ok_note = ""
    if ctx["ok"]:
        ok_note = "\n\nThese files were processed successfully:\n" + "\n".join(
            "  - %s (reference %s)" % (name, i) for name, i in ctx["ok"])

    if category == "DOC_SUBMISSION":
        return ("%s\n\nWe received your file(s) and processed them successfully.\n\n"
                "Reference: %s\nFiles: %s\n\nPlease keep the reference if you need to contact us."
                % (hello, refs, files))

    if category == "NO_ATTACHMENT":
        return ("%s\n\nYour mail reached us, but there was no attachment. Please reply to this mail "
                "with your document attached as a PDF or an image (JPG, PNG, TIFF, BMP or WEBP)." % hello)

    if category == "UNSUPPORTED_ATTACHMENT":
        return ("%s\n\nWe could not accept these files:\n%s\n\nWe can only read PDF files and images "
                "(JPG, PNG, TIFF, BMP, WEBP). Please convert the file and send it again.%s"
                % (hello, problems, ok_note))

    if category == "PROTECTED_OR_TOO_LARGE":
        return ("%s\n\nWe could not open these files:\n%s\n\nPlease send an unprotected copy, or a smaller "
                "one (up to %d MB), as a reply to this mail.%s"
                % (hello, problems, classifier.MAX_FILE_MB, ok_note))

    if category == "DOC_FAILED":
        return ("%s\n\nWe could not read these files even after several tries:\n%s\n\nPlease send them "
                "again as a clear, well-lit scan or the original PDF.%s" % (hello, problems, ok_note))

    if category == "NEEDS_HUMAN":
        return ("%s\n\nThank you for your message. A person from our team will read it and reply soon.\n\n"
                "Reference: %s" % (hello, ctx["email_id"]))

    return None


def send_reply(service, mail: dict, category: str, ctx: dict, email_id: int, my_address: str):

    """ Check the rules, build the reply, send it in the same thread and save the result. """

    ok, why = can_reply(mail, category, my_address)
    if not ok:
        print("  No reply: %s" % why)
        store.set_reply(email_id, "not_needed")
        return

    body = build_reply(category, mail, ctx)

    msg = EmailMessage()
    msg["To"] = recipient(mail)
    msg["Subject"] = reply_subject(mail)
    if mail["message_id"]:
        msg["In-Reply-To"] = mail["message_id"]
        msg["References"] = (mail["references"] + " " + mail["message_id"]).strip()
    msg["Auto-Submitted"] = "auto-replied"   # stops other auto-responders from answering us
    msg.set_content(body)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    try:
        sent = service.users().messages().send(
            userId="me", body={"raw": raw, "threadId": mail["thread_id"]}
        ).execute()
        store.set_reply(email_id, "sent", sent["id"])
        print("  Reply sent (%s)" % category)
    except Exception as e:
        store.set_reply(email_id, "failed")
        print("  Reply FAILED: %s" % e)