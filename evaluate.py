"""
Run the test emails in test_emails.json through the real classifier and reply rules,
and compare the results with the expected answers.

Usage:
    python evaluate.py            show a short report
    python evaluate.py -v         also show every passing case
    python evaluate.py T07 T31    run only these cases
"""

import json
import os
import sys
import tempfile

import classifier
import replies
import store


HERE = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(HERE, "test_emails.json")


def build_mail(case: dict) -> dict:

    """ Fill in the fields that mail_parser.parse_message would give. """

    m = case["mail"]
    return {
        "id": "msg_" + case["id"],
        "thread_id": "thr_" + case["id"],
        "sender_name": m.get("sender_name", ""),
        "sender_email": m["sender_email"].lower(),
        "reply_to_email": m.get("reply_to_email", "").lower(),
        "subject": m.get("subject", ""),
        "date": "Mon, 19 Oct 2026 10:30:00 +0530",
        "message_id": "<%s@test>" % case["id"],
        "references": "",
        "headers": {k.lower(): v for k, v in m.get("headers", {}).items()},
        "body": m.get("body", ""),
        "attachments": [
            {"filename": a["filename"], "size": a["size_bytes"], "attachment_id": None, "data": None}
            for a in m.get("attachments", [])
        ],
    }


def apply_setup(case: dict, mail: dict):

    """ Put the database in the state the case describes. """

    s = case.get("setup", {})

    if s.get("already_processed"):
        email_id = store.start_email(mail)
        store.finish_email(email_id, "DOC_SUBMISSION")

    if s.get("blocked_sender"):
        store.block_sender(mail["sender_email"])

    def old_reply(index, category):
        old = dict(mail, id="old_%s_%d" % (case["id"], index))
        email_id = store.start_email(old)
        store.finish_email(email_id, category, "pending")
        store.set_reply(email_id, "sent", "old_reply_%d" % index)

    for i in range(s.get("replies_today", 0)):
        old_reply(i, "NEEDS_HUMAN")           # other category, so only the daily limit applies

    if s.get("replied_same_category_recently"):
        old_reply(99, case["expected"]["category"])


def classify(case: dict, mail: dict):

    """ Same steps as main.py will do, with the file results taken from the case. """

    pre = classifier.pre_classify(mail)
    if pre:
        return pre, []

    usable, unsupported, too_large = classifier.sort_attachments(mail)
    outcomes = [{"file": a["filename"], "outcome": "unsupported"} for a in unsupported]
    outcomes += [{"file": a["filename"], "outcome": "too_large"} for a in too_large]

    doc_id = 100
    for a in usable:
        outcome = case.get("processing", {}).get(a["filename"], "ok")
        o = {"file": a["filename"], "outcome": outcome}
        if outcome in ("ok", "failed", "protected"):
            doc_id += 1
            o["doc_id"] = doc_id
        outcomes.append(o)

    return classifier.final_category(mail, outcomes), outcomes


def run_case(case: dict, tmp_dir: str, my_address: str) -> list:

    """ Run one case and return a list of problems (empty list = pass). """

    store.DB_PATH = os.path.join(tmp_dir, case["id"] + ".db")
    store.init_db()

    mail = build_mail(case)
    apply_setup(case, mail)

    category, outcomes = classify(case, mail)
    allowed, why = replies.can_reply(mail, category, my_address)

    exp = case["expected"]
    problems = []

    if category != exp["category"]:
        problems.append("category: got %s, expected %s" % (category, exp["category"]))

    if allowed != exp["reply"]:
        problems.append("reply: got %s (%s), expected %s" % (allowed, why, exp["reply"]))

    if allowed and exp["reply"]:
        if "reply_to" in exp and replies.recipient(mail) != exp["reply_to"]:
            problems.append("reply goes to %s, expected %s" % (replies.recipient(mail), exp["reply_to"]))

        body = replies.build_reply(category, mail, replies.make_context(outcomes, email_id=1))
        if body is None:
            problems.append("no reply text exists for category %s" % category)
        else:
            for text in exp.get("reply_contains", []):
                if text not in body:
                    problems.append("reply is missing the text: %r" % text)

    return problems


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    verbose = "-v" in sys.argv

    with open(DATA_FILE, encoding="utf-8") as f:
        data = json.load(f)

    cases = [c for c in data["cases"] if not args or c["id"] in args]
    my_address = data["my_address"]

    passed, failed = 0, []
    by_group = {}

    with tempfile.TemporaryDirectory() as tmp_dir:
        for case in cases:
            problems = run_case(case, tmp_dir, my_address)
            group = by_group.setdefault(case["group"], [0, 0])
            group[1] += 1

            if problems:
                failed.append((case, problems))
                print("FAIL  %s  %s" % (case["id"], case["description"]))
                for p in problems:
                    print("        - " + p)
            else:
                passed += 1
                group[0] += 1
                if verbose:
                    print("pass  %s  %-24s %s" % (case["id"], case["expected"]["category"], case["description"]))

    print()
    print("Results by group")
    print("----------------")
    for group, (ok, total) in by_group.items():
        print("  %-24s %d / %d" % (group, ok, total))
    print()
    print("Total: %d passed, %d failed, %d cases" % (passed, len(failed), len(cases)))

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
