"""
Fields and rules.

A field is a value found in a document or mail with a regular expression.
A rule is "when these lines are true, do this" (see config.yaml for the format).
No eval() is used: conditions are parsed by hand, so config.yaml cannot run code.
"""

import re
from dataclasses import dataclass, field

BUILTINS = ("category", "sender", "subject", "body", "text", "filename", "file_count", "ok_count")

_WORD_OPS = "not contains|not matches|not in|contains|matches|exists|missing|in"
_COND_SYMBOL = re.compile(r"^\s*([A-Za-z_]\w*)\s*(==|!=|>=|<=|>|<)\s*(.+?)\s*$", re.S)
_COND_WORD = re.compile(r"^\s*([A-Za-z_]\w*)\s+(%s)(?:\s+(.+?))?\s*$" % _WORD_OPS, re.S)
_NUMBER = re.compile(r"^[-+]?\d[\d,]*(?:\.\d+)?$")


# ---------------------------------------------------------------- numbers and text

def to_number(value):

    """ 12,400.50 or 'Rs. 12,400' -> 12400.5.  Returns None if it is not a number. """

    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = re.sub(r"[,\s]", "", str(value))
    s = re.sub(r"^[^\d+\-]+", "", s)           # leading currency such as Rs. or ₹
    return float(s) if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", s) else None


def format_value(value) -> str:

    """ How a value looks inside a reply. """

    if value is None:
        return ""
    if isinstance(value, float):
        return f"{int(value):,}" if value == int(value) else f"{value:,.2f}"
    return str(value)


# ---------------------------------------------------------------- fields

def extract_value(spec: dict, text: str):

    """ Find one field in a text. Returns the value, or None if not found. """

    matches = list(re.finditer(spec["pattern"], text or "", re.IGNORECASE | re.MULTILINE))
    if spec.get("match", "first") == "last":
        matches.reverse()

    for m in matches:
        raw = m.group(1) if m.re.groups else m.group(0)
        if raw is None:
            continue
        raw = " ".join(raw.split())
        if spec.get("type", "text") == "number":
            number = to_number(raw)
            if number is not None:
                return number
        elif raw:
            return raw
    return None


def extract_doc_fields(fields_cfg: dict, text: str) -> dict:

    """ Fields that live in documents. """

    return {name: extract_value(spec, text)
            for name, spec in fields_cfg.items() if spec.get("source", "document") == "document"}


def extract_mail_fields(fields_cfg: dict, mail: dict) -> dict:

    """ Fields that live in the mail itself. """

    out = {}
    for name, spec in fields_cfg.items():
        source = spec.get("source", "document")
        if source == "email":
            out[name] = extract_value(spec, mail["subject"] + "\n" + mail["body"])
        elif source == "subject":
            out[name] = extract_value(spec, mail["subject"])
    return out


def build_values(fields_cfg: dict, mail: dict, category: str, ok_docs: list) -> dict:

    """
    Everything a rule can look at: built-in names plus all fields.
    A document field takes its value from the first document that has it.
    ok_docs: list of dicts with "file", "text" and "fields".
    """

    values = {name: None for name in fields_cfg}
    values.update(extract_mail_fields(fields_cfg, mail))

    for doc in ok_docs:
        for name, value in doc.get("fields", {}).items():
            if values.get(name) is None and value is not None:
                values[name] = value

    values.update({
        "category": category,
        "sender": mail["sender_email"],
        "subject": mail["subject"],
        "body": mail["body"],
        "text": "\n".join(d["text"] for d in ok_docs),
        "filename": ok_docs[0]["file"] if ok_docs else (mail["attachments"][0]["filename"] if mail["attachments"] else ""),
        "file_count": len(mail["attachments"]),
        "ok_count": len(ok_docs),
    })
    return values


# ---------------------------------------------------------------- conditions

def parse_condition(text: str):

    """ 'invoice_total > 50000' -> ('invoice_total', '>', '50000'). Raises ValueError if it makes no sense. """

    m = _COND_SYMBOL.match(text) or _COND_WORD.match(text)
    if not m:
        raise ValueError("cannot read this line: %r. Use  <name> <test> <value>" % text)

    left, op, right = m.group(1), m.group(2), m.group(3)
    if op in ("exists", "missing"):
        if right:
            raise ValueError("%r does not take a value" % op)
    elif not right:
        raise ValueError("%r needs a value after it" % op)
    return left, op, right


def _resolve(token: str, values: dict):
    t = token.strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
        return t[1:-1]
    if t in values:
        return values[t]                       # another field: this is how two things are compared
    if _NUMBER.match(t):
        return float(t.replace(",", ""))
    return t


def _same(a, b) -> bool:
    na, nb = to_number(a), to_number(b)
    numeric_type = isinstance(a, (int, float)) or isinstance(b, (int, float))
    if numeric_type and na is not None and nb is not None:
        return abs(na - nb) < 1e-9
    return str(a).strip().lower() == str(b).strip().lower()


def evaluate_condition(text: str, values: dict) -> bool:
    left, op, right = parse_condition(text)
    a = values.get(left)

    if op == "exists":
        return a is not None and str(a).strip() != ""
    if op == "missing":
        return a is None or str(a).strip() == ""

    if a is None:
        return False                           # a value is missing, so the line is false

    negate = op.startswith("not ")
    base = op[4:] if negate else op

    if base in ("in",):
        items = [_resolve(part, values) for part in right.split(",")]
        if any(i is None for i in items):
            return False
        result = any(_same(a, i) for i in items)
        return (not result) if negate else result

    b = _resolve(right, values)
    if b is None:
        return False

    if base == "==":
        return _same(a, b)
    if base == "!=":
        return not _same(a, b)
    if base in (">", ">=", "<", "<="):
        na, nb = to_number(a), to_number(b)
        if na is None or nb is None:
            return False
        return {">": na > nb, ">=": na >= nb, "<": na < nb, "<=": na <= nb}[base]
    if base == "contains":
        result = str(b).lower() in str(a).lower()
    elif base == "matches":
        try:
            result = re.search(str(b), str(a), re.IGNORECASE | re.MULTILINE) is not None
        except re.error:
            return False
    else:
        return False
    return (not result) if negate else result


# ---------------------------------------------------------------- rules

@dataclass
class Effects:
    category: str = None
    replace: str = None
    notes: list = field(default_factory=list)
    no_reply: bool = False
    flags: list = field(default_factory=list)
    matched: list = field(default_factory=list)


def _conditions(rule: dict) -> list:
    when = rule.get("when") or []
    return [when] if isinstance(when, str) else list(when)


def apply_rules(rules_cfg: list, values: dict) -> Effects:
    fx = Effects()
    for rule in rules_cfg or []:
        if rule.get("enabled", True) is False:
            continue
        try:
            if not all(evaluate_condition(str(c), values) for c in _conditions(rule)):
                continue
        except ValueError:
            continue                            # config validation already reports this

        fx.matched.append(rule.get("name", "(unnamed rule)"))

        if rule.get("category") and fx.category is None:
            fx.category = str(rule["category"])
        if rule.get("no_reply"):
            fx.no_reply = True
        if rule.get("flag"):
            fx.flags.append(rule["flag"] if isinstance(rule["flag"], str) else rule.get("name", "flagged by rule"))
        if rule.get("reply"):
            if rule.get("mode", "append") == "replace":
                if fx.replace is None:
                    fx.replace = str(rule["reply"])
            else:
                fx.notes.append(str(rule["reply"]).strip())
    return fx


def check_rules(rules_cfg, known_names: set) -> list:

    """ Returns a list of problems in the rules section (empty list = fine). """

    errors = []
    if rules_cfg is None:
        return errors
    if not isinstance(rules_cfg, list):
        return ["'rules' must be a list"]

    for i, rule in enumerate(rules_cfg, 1):
        label = "rule %d" % i
        if not isinstance(rule, dict):
            errors.append("%s: must be a set of keys (name, when, reply, ...)" % label)
            continue
        label = "rule %d (%s)" % (i, rule.get("name", "no name"))

        unknown = set(rule) - {"name", "enabled", "when", "mode", "reply", "no_reply", "flag", "category"}
        if unknown:
            errors.append("%s: unknown key(s): %s" % (label, ", ".join(sorted(unknown))))

        conds = _conditions(rule)
        if not conds:
            errors.append("%s: 'when' needs at least one line" % label)
        for c in conds:
            try:
                left, _, _ = parse_condition(str(c))
                if left not in known_names:
                    errors.append("%s: unknown name %r in %r. Known: %s" % (label, left, c, ", ".join(sorted(known_names))))
            except ValueError as e:
                errors.append("%s: %s" % (label, e))

        mode = rule.get("mode", "append")
        if mode not in ("append", "replace"):
            errors.append("%s: mode must be append or replace" % label)
        if mode == "replace" and not rule.get("reply"):
            errors.append("%s: mode replace needs a reply text" % label)
        if not any(rule.get(k) for k in ("reply", "no_reply", "flag", "category")):
            errors.append("%s: it does nothing. Add reply, no_reply, flag or category" % label)
    return errors
