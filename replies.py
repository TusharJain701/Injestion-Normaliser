import base64
import re
from email.message import EmailMessage

import classifier
import config
import rules
import store


class _Safe(dict):
    """A {name} that is not known stays visible in the reply, so a typo is easy to spot."""
    def __missing__(self, key):
        return "{" + key + "}"


def get_my_address(service) -> str:

    """ Our own Gmail address, so we never reply to ourselves. """

    return service.users().getProfile(userId="me").execute(num_retries=3)["emailAddress"].lower()


def recipient(mail: dict) -> str:

    """ Reply-To if the mail has one, otherwise From. """

    return mail["reply_to_email"] or mail["sender_email"]


def reply_subject(mail: dict) -> str:
    subject = mail["subject"].strip() or "(no subject)"
    return subject if subject.lower().startswith("re:") else "Re: " + subject


def problem_reason(outcome: str) -> str:
    return {
        "unsupported": "not a supported file type",
        "too_large": "larger than %s MB" % config.setting("max_file_mb"),
        "protected": "password protected",
        "failed": "could not be read",
    }[outcome]


def make_context(outcomes: list, email_id: int) -> dict:

    """ Collect what a reply needs: processed files, problem files and the mail id. """

    ok = [(o["file"], o["doc_id"]) for o in outcomes if o["outcome"] == "ok"]
    problems = [(o["file"], problem_reason(o["outcome"]))
                for o in outcomes if o["outcome"] in ("unsupported", "too_large", "protected", "failed")]
    return {"ok": ok, "problems": problems, "email_id": email_id}


# ---------------------------------------------------------------- the rules for sending

def can_reply(mail: dict, category: str, my_address: str):

    """ Apply the reply rules. Returns (True, "ok") or (False, reason). """

    s = config.get()["settings"]

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

    allowed = [str(a).lower() for a in s["allowed_senders"]]
    if allowed and not any(to == a or to.endswith(a) for a in allowed):
        return False, "sender is not on the allowed list"

    limit = int(s["max_replies_per_sender_per_day"])
    if store.replies_last_day(mail["sender_email"]) >= limit:
        return False, "already %d replies to this sender today" % limit

    if store.replied_recently(mail["sender_email"], category, int(s["same_category_cooldown_minutes"])):
        return False, "same category was answered recently"

    return True, "ok"


# ---------------------------------------------------------------- building the text

def placeholders(mail: dict, category: str, ctx: dict, values: dict = None) -> dict:
    cfg = config.get()
    reply = cfg["reply"]

    full_name = mail["sender_name"].strip().strip('"')
    first = full_name.split()[0] if full_name else ""
    greeting = (reply["greeting_named"].format_map(_Safe(first_name=first, name=full_name))
                if first else reply["greeting_plain"])

    ok = ctx["ok"]
    ph = {
        "greeting": greeting,
        "first_name": first,
        "name": full_name,
        "sender": mail["sender_email"],
        "subject": mail["subject"],
        "signature": reply["signature"].strip(),
        "files": ", ".join(name for name, _ in ok),
        "references": ", ".join(str(i) for _, i in ok),
        "problems": "\n".join("  - %s: %s" % (name, why) for name, why in ctx["problems"]),
        "ok_note": ("These files were processed successfully:\n"
                    + "\n".join("  - %s (reference %s)" % (name, i) for name, i in ok)) if ok else "",
        "email_id": ctx["email_id"],
        "category": category,
        "max_file_mb": config.setting("max_file_mb"),
        "rule_notes": "",
    }
    for field_name in cfg["fields"]:
        ph[field_name] = rules.format_value((values or {}).get(field_name))
    return ph


def render(text: str, ph: dict) -> str:
    try:
        return text.format_map(_Safe(ph))
    except (ValueError, IndexError, KeyError) as e:
        print("  Warning: could not fill in a template (%s). It is sent as written." % e)
        return text


def tidy(text: str) -> str:
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def compose_reply(category: str, mail: dict, ctx: dict, values: dict = None, effects=None):

    """ Returns (subject, body), or None when the category has no template and no rule supplies a text. """

    cfg = config.get()
    ph = placeholders(mail, category, ctx, values)

    notes = "\n\n".join(render(n, ph) for n in (effects.notes if effects else []))
    ph["rule_notes"] = notes

    template = cfg["templates"].get(category)
    if effects is not None and effects.replace is not None:
        body_text, subject_text = effects.replace, None
    elif template:
        body_text, subject_text = template["body"], template.get("subject")
    else:
        return None

    body = render(body_text, ph)
    if notes and "{rule_notes}" not in body_text:
        body = body.rstrip() + "\n\n" + notes          # the text has no {rule_notes} spot, so add at the end

    subject = render(subject_text, ph) if subject_text else reply_subject(mail)
    return subject.strip(), tidy(body)


def build_reply(category: str, mail: dict, ctx: dict, values: dict = None, effects=None):

    """ Only the body of the reply (or None). """

    composed = compose_reply(category, mail, ctx, values, effects)
    return composed[1] if composed else None


# ---------------------------------------------------------------- sending

def _send(service, message: EmailMessage, thread_id=None) -> str:
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    body = {"raw": raw}
    if thread_id:
        body["threadId"] = thread_id
    return service.users().messages().send(userId="me", body=body).execute(num_retries=3)["id"]


def send_reply(service, mail: dict, category: str, ctx: dict, email_id: int, my_address: str,
               values: dict = None, effects=None, dry_run: bool = False) -> str:

    """
    Check the rules, build the reply, send it in the same thread and save the result.
    Returns "sent", "failed", "dry_run" or "not_needed".
    """

    if effects is not None and effects.no_reply:
        print("  No reply: rule '%s' says so" % ", ".join(effects.matched))
        store.set_reply(email_id, "not_needed")
        return "not_needed"

    ok, why = can_reply(mail, category, my_address)
    if not ok:
        print("  No reply: %s" % why)
        store.set_reply(email_id, "not_needed")
        return "not_needed"

    composed = compose_reply(category, mail, ctx, values, effects)
    if composed is None:
        print("  No reply: there is no template for %s in config.yaml" % category)
        store.set_reply(email_id, "not_needed")
        return "not_needed"
    subject, body = composed

    msg = EmailMessage()
    msg["To"] = recipient(mail)
    msg["Subject"] = subject
    if mail["message_id"]:
        msg["In-Reply-To"] = mail["message_id"]
        msg["References"] = (mail["references"] + " " + mail["message_id"]).strip()
    msg["Auto-Submitted"] = "auto-replied"      # stops other auto-responders from answering us
    msg.set_content(body)

    if dry_run:
        print("  DRY RUN, would send to %s:\n    Subject: %s\n    %s" % (msg["To"], subject, body.replace("\n", "\n    ")))
        store.set_reply(email_id, "dry_run")
        return "dry_run"

    try:
        sent_id = _send(service, msg, mail["thread_id"])
        store.set_reply(email_id, "sent", sent_id)
        print("  Reply sent (%s)" % category)
        return "sent"
    except Exception as e:
        store.set_reply(email_id, "failed")
        print("  Reply FAILED: %s" % e)
        return "failed"


def send_alert(service, to: str, subject: str, body: str, dry_run: bool = False):

    """ A short note to the admin, not part of any thread. """

    if dry_run:
        print("  DRY RUN, would alert %s: %s" % (to, subject))
        return
    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject
    msg["Auto-Submitted"] = "auto-generated"
    msg.set_content(body)
    try:
        _send(service, msg)
    except Exception as e:
        print("  Alert FAILED: %s" % e)
