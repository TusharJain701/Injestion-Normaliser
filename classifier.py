import re

import config
import store


ALLOWED_EXTS = (".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp")
DANGEROUS_EXTS = (".exe", ".js", ".bat", ".cmd", ".com", ".scr", ".vbs", ".msi", ".jar", ".ps1", ".lnk", ".dll", ".hta")

# Categories that never get a reply
NO_REPLY_CATEGORIES = ("AUTO_GENERATED", "SUSPICIOUS", "DUPLICATE")

AUTO_SENDER = re.compile(r"(no[-_.]?reply|do[-_.]?not[-_.]?reply|mailer-daemon|postmaster)", re.I)
AUTO_SUBJECT_STARTS = ("out of office", "automatic reply", "undeliverable")


def is_auto_generated(mail: dict) -> bool:

    """ Robots, newsletters, bounces and out-of-office mails. """

    h = mail["headers"]

    if AUTO_SENDER.search(mail["sender_email"]):
        return True

    auto = h.get("auto-submitted", "").strip().lower()
    if auto and auto != "no":
        return True

    if h.get("precedence", "").strip().lower() in ("bulk", "junk", "list"):
        return True

    if "list-id" in h or "list-unsubscribe" in h:
        return True

    return mail["subject"].strip().lower().startswith(AUTO_SUBJECT_STARTS)


def is_suspicious(mail: dict) -> bool:

    """ Failed sender checks, blocked sender, or a dangerous file type. """

    auth = mail["headers"].get("authentication-results", "").lower()
    if re.search(r"\b(spf|dkim|dmarc)=fail\b", auth):
        return True

    if store.is_blocked(mail["sender_email"]):
        return True

    return any(a["filename"].lower().endswith(DANGEROUS_EXTS) for a in mail["attachments"])


def pre_classify(mail: dict):

    """
    First checks, done before any attachment is downloaded.
    Returns AUTO_GENERATED, SUSPICIOUS, DUPLICATE, or None (keep going).
    """

    if is_auto_generated(mail):
        return "AUTO_GENERATED"
    if is_suspicious(mail):
        return "SUSPICIOUS"
    if store.email_done(mail["id"]):
        return "DUPLICATE"
    return None


def sort_attachments(mail: dict):

    """ Split attachments into (usable, unsupported, too_large). """

    usable, unsupported, too_large = [], [], []
    for att in mail["attachments"]:
        name = att["filename"].lower()
        if not name.endswith(ALLOWED_EXTS):
            unsupported.append(att)
        elif att["size"] > config.setting("max_file_mb") * 1024 * 1024:
            too_large.append(att)
        else:
            usable.append(att)
    return usable, unsupported, too_large


def needs_human(mail: dict, got_ok_file: bool) -> bool:
    text = (mail["subject"] + " " + mail["body"]).lower()
    words = [str(w).lower() for w in config.setting("needs_human_words")]
    if any(re.search(r"\b" + re.escape(w) + r"\b", text) for w in words):
        return True
    return mail["subject"].strip().endswith("?") and not got_ok_file


def final_category(mail: dict, outcomes: list) -> str:

    """
    Decide the category after the attachments were handled.
    outcomes: list of dicts with "outcome" = ok | failed | protected | too_large | unsupported | file_duplicate
    """

    kinds = [o["outcome"] for o in outcomes]
    got_ok = "ok" in kinds

    if needs_human(mail, got_ok):
        return "NEEDS_HUMAN"
    if not mail["attachments"]:
        return "NO_ATTACHMENT"
    if "protected" in kinds or "too_large" in kinds:
        return "PROTECTED_OR_TOO_LARGE"
    if "failed" in kinds:
        return "DOC_FAILED"
    if "unsupported" in kinds:
        return "UNSUPPORTED_ATTACHMENT"
    if got_ok:
        return "DOC_SUBMISSION"
    return "DUPLICATE"  # only files we already had
