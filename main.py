"""
Ingestion Normaliser

  python main.py             watch the inbox and handle every new mail
  python main.py --once      check the inbox one time and stop
  python main.py --dry-run   show what would happen: nothing is sent, nothing is marked as read,
                             and the files and database of a dry run are kept apart

For every unread mail: classify it, save attachments as JSON (text, tables, fields),
and reply according to config.yaml.
"""

import argparse
import hashlib
import os
import sys
import time
import traceback

import classifier
import config
import email_aquire
import extract
import json_process
import ocr_process
import replies
import rules
import store

FAIL_LIMIT = 3          # a mail that crashes the handler this many times is skipped
_failures = {}


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def process_document(path: str) -> dict:

    """ Read one saved file, trying again if it fails. Returns {"status": ok | failed | protected, ...}. """

    attempts = int(config.setting("max_attempts"))
    error = "unknown error"
    for attempt in range(1, attempts + 1):
        try:
            return {"status": "ok", "result": extract.extract_file(path)}
        except extract.ProtectedError as e:
            return {"status": "protected", "error": str(e)}
        except extract.NoTextError as e:
            return {"status": "failed", "error": str(e)}        # trying again will not help
        except Exception as e:
            error = "%s: %s" % (type(e).__name__, e)
            print("    attempt %d/%d failed: %s" % (attempt, attempts, error))
    return {"status": "failed", "error": error}


def handle_attachment(service, mail: dict, att: dict, email_id: int, mail_info: dict) -> dict:
    name = att["filename"]

    try:
        path = email_aquire.download_attachment(service, mail, att, config.setting("attachments_dir"))
    except Exception as e:
        print("  %s: download failed (%s)" % (name, e))
        doc_id = store.add_document(email_id, name, "", None, None, "failed", "download failed: %s" % e)
        return {"file": name, "outcome": "failed", "doc_id": doc_id}

    file_hash = sha256(path)
    if store.has_hash(file_hash):
        os.remove(path)
        print("  %s: same file was processed before, skipped" % name)
        return {"file": name, "outcome": "file_duplicate"}

    res = process_document(path)

    if res["status"] == "ok":
        result = res["result"]
        doc_fields = rules.extract_doc_fields(config.get()["fields"], result["text"])
        mail_info = dict(mail_info)
        json_path = json_process.save_result(result, path, config.setting("output_dir"), mail_info, doc_fields)
        doc_id = store.add_document(email_id, name, path, file_hash, result["type"], "completed", json_path=json_path)
        print("  %s: %s, %d page(s), %d table(s), %d words -> %s" % (
            name, result["type"], len(result["pages"]), len(result["tables"]), len(result["text"].split()),
            os.path.basename(json_path)))
        return {"file": name, "outcome": "ok", "doc_id": doc_id, "text": result["text"],
                "fields": doc_fields, "json_path": json_path}

    outcome = "protected" if res["status"] == "protected" else "failed"
    doc_id = store.add_document(email_id, name, path, file_hash, None, "failed", res["error"])
    print("  %s: %s (%s)" % (name, outcome, res["error"]))
    return {"file": name, "outcome": outcome, "doc_id": doc_id}


def handle_mail(service, mail: dict, my_address: str, dry_run: bool = False):
    print("\nMail from %s: %s" % (mail["sender_email"], mail["subject"] or "(no subject)"))
    cfg = config.get()

    # Step 1: checks that need no download
    category = classifier.pre_classify(mail)
    if category == "DUPLICATE":
        print("  Already handled, skipped")
        return
    email_id = store.start_email(mail)
    if category in ("AUTO_GENERATED", "SUSPICIOUS"):
        store.finish_email(email_id, category)
        print("  %s: no reply, attachments not opened" % category)
        return

    # Step 2: read every attachment
    usable, unsupported, too_large = classifier.sort_attachments(mail)
    outcomes = [{"file": a["filename"], "outcome": "unsupported"} for a in unsupported]
    outcomes += [{"file": a["filename"], "outcome": "too_large"} for a in too_large]
    mail_info = {"sender": mail["headers"].get("from"), "subject": mail["subject"], "date": mail["date"]}
    for att in usable:
        outcomes.append(handle_attachment(service, mail, att, email_id, mail_info))

    # Step 3: category, then the rules from config.yaml
    category = classifier.final_category(mail, outcomes)
    ok_docs = [o for o in outcomes if o["outcome"] == "ok"]
    values = rules.build_values(cfg["fields"], mail, category, ok_docs)
    effects = rules.apply_rules(cfg["rules"], values)
    if effects.matched:
        print("  Rules fired: %s" % ", ".join(effects.matched))
    if effects.category:
        category = effects.category
    print("  Category: %s" % category)

    # Step 4: flag for a person
    reasons = list(effects.flags)
    if category == "NEEDS_HUMAN":
        reasons.append("the mail needs a person")
    if category == "DOC_FAILED":
        reasons.append("a document could not be read")
    if reasons:
        store.flag_email(email_id, "; ".join(reasons))
        print("  FLAGGED: %s" % "; ".join(reasons))

    # Step 5: reply
    status = "not_needed"
    if category not in classifier.NO_REPLY_CATEGORIES:
        store.finish_email(email_id, category, "pending")
        ctx = replies.make_context(outcomes, email_id)
        status = replies.send_reply(service, mail, category, ctx, email_id, my_address, values, effects, dry_run)
    else:
        store.finish_email(email_id, category)
        print("  No reply for this category")

    # Step 6: tell the admin about failed documents
    alert_to = config.setting("alert_email")
    if category == "DOC_FAILED" and alert_to:
        failed = ", ".join(o["file"] for o in outcomes if o["outcome"] == "failed")
        replies.send_alert(service, alert_to, "Document failed: %s" % failed,
                           "Mail from %s, subject: %s\nFailed files: %s\nMail id: %s" % (
                               mail["sender_email"], mail["subject"], failed, email_id), dry_run)

    # Step 7: write the final category into the JSON files
    for o in ok_docs:
        json_process.update_mail(o["json_path"], category=category, reply_status=status)


def run_once(service, my_address: str, dry_run: bool):
    for mail in email_aquire.fetch_unread(service):
        try:
            handle_mail(service, mail, my_address, dry_run)
            if not dry_run:
                email_aquire.mark_read(service, mail["id"])
        except Exception:
            _failures[mail["id"]] = _failures.get(mail["id"], 0) + 1
            print("  ERROR while handling this mail (try %d of %d):" % (_failures[mail["id"]], FAIL_LIMIT))
            traceback.print_exc()
            if _failures[mail["id"]] >= FAIL_LIMIT and not dry_run:
                print("  Giving up on this mail and marking it as read.")
                try:
                    email_aquire.mark_read(service, mail["id"])
                except Exception:
                    pass


def use_dry_run_folders():

    """ A dry run keeps its files and database apart from the real ones. """

    s = config.get()["settings"]
    s["attachments_dir"] = os.path.join(s["attachments_dir"], "dry_run")
    s["output_dir"] = os.path.join(s["output_dir"], "dry_run")
    s["database"] = s["database"] + ".dryrun"


def main():
    parser = argparse.ArgumentParser(description="Ingestion Normaliser")
    parser.add_argument("--once", action="store_true", help="check the inbox one time and stop")
    parser.add_argument("--dry-run", action="store_true", help="send nothing and mark nothing as read")
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):        # a Windows console cannot print every character
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass

    try:
        config.load()
    except config.ConfigError as e:
        print(e)
        sys.exit(1)

    if args.dry_run:
        use_dry_run_folders()
        if os.path.exists(config.setting("database")):
            os.remove(config.setting("database"))
        print("DRY RUN: nothing will be sent and nothing will be marked as read.")

    store.DB_PATH = config.setting("database")
    store.init_db()

    version = ocr_process.tesseract_version()
    if version:
        print("Tesseract %s found." % version)
    else:
        print("WARNING: Tesseract was not found. Scanned PDFs and images will fail.\n"
              "         Install it, or set settings.tesseract_cmd in config.yaml.")

    service = email_aquire.get_service()
    my_address = replies.get_my_address(service)
    enabled = [r["name"] for r in config.get()["rules"] if r.get("enabled", True) is not False]
    print("Signed in as %s. %d rule(s) active. Checking every %s s. Press Ctrl+C to stop." % (
        my_address, len(enabled), config.setting("poll_interval_seconds")))

    try:
        while True:
            if config.reload_if_changed() and args.dry_run:
                use_dry_run_folders()
            try:
                run_once(service, my_address, args.dry_run)
            except Exception:
                traceback.print_exc()       # for example no internet: wait and try again
            if args.once:
                break
            time.sleep(config.setting("poll_interval_seconds"))
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
