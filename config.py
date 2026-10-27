"""
Loads and checks config.yaml.  Other modules use:
    config.get()            the whole config
    config.setting("name")  one value from the settings section
    config.reload_if_changed()   re-read the file if it was saved since last time
"""

import os
import string
import re
import yaml

import rules

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.environ.get("INGEST_CONFIG", os.path.join(BASE_DIR, "config.yaml"))


class ConfigError(Exception):
    pass


DEFAULT_SETTINGS = {
    "poll_interval_seconds": 30,
    "max_file_mb": 20,
    "max_attempts": 3,
    "max_replies_per_sender_per_day": 5,
    "same_category_cooldown_minutes": 60,
    "allowed_senders": [],
    "needs_human_words": ["urgent", "complaint", "refund", "call me"],
    "alert_email": "",
    "tesseract_cmd": "",
    "ocr_language": "eng",
    "ocr_dpi": 300,
    "min_digital_chars": 50,
    "attachments_dir": "attachments",
    "output_dir": "output",
    "database": "ingestion.db",
}
DEFAULT_REPLY = {
    "greeting_named": "Hello {first_name},",
    "greeting_plain": "Hello,",
    "signature": "Regards,\nIngestion Normaliser",
}

# Names that can appear inside { } in templates and rule replies
PLACEHOLDERS = {"greeting", "first_name", "name", "sender", "subject", "signature", "files", "references",
                "problems", "ok_note", "rule_notes", "email_id", "category", "max_file_mb"}

_PATH_SETTINGS = ("attachments_dir", "output_dir", "database")
_cfg = None
_mtime = None
_failed_mtime = None


def _placeholders_in(text: str) -> set:
    names = set()
    for _, name, _, _ in string.Formatter().parse(text):
        if name is not None:
            names.add(name)
    return names


def _check_text(label: str, text, allowed: set, errors: list):
    if not isinstance(text, str):
        errors.append("%s: must be text" % label)
        return
    try:
        used = _placeholders_in(text)
    except ValueError as e:
        errors.append("%s: curly brackets are not balanced (%s). Write {{ and }} for a real bracket" % (label, e))
        return
    for name in sorted(used - allowed):
        errors.append("%s: unknown name {%s}. You can use: %s" % (label, name, ", ".join(sorted(allowed))))


def _validate(raw: dict) -> tuple[dict, list]:
    errors = []

    settings = dict(DEFAULT_SETTINGS)
    given = raw.get("settings") or {}
    for key, value in given.items():
        if key not in DEFAULT_SETTINGS:
            errors.append("settings: unknown setting %r. Known: %s" % (key, ", ".join(DEFAULT_SETTINGS)))
        else:
            settings[key] = value

    for key in ("poll_interval_seconds", "max_file_mb", "max_attempts", "max_replies_per_sender_per_day",
                "same_category_cooldown_minutes", "ocr_dpi", "min_digital_chars"):
        v = settings[key]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
            errors.append("settings.%s must be a number, 0 or more" % key)
    if isinstance(settings["max_attempts"], (int, float)) and settings["max_attempts"] < 1:
        errors.append("settings.max_attempts must be at least 1")
    for key in ("allowed_senders", "needs_human_words"):
        if not isinstance(settings[key], list):
            errors.append("settings.%s must be a list" % key)

    reply = dict(DEFAULT_REPLY)
    reply.update(raw.get("reply") or {})
    for key in ("greeting_named", "greeting_plain", "signature"):
        _check_text("reply.%s" % key, reply[key], {"first_name", "name"}, errors)

    fields_cfg = raw.get("fields") or {}
    if not isinstance(fields_cfg, dict):
        errors.append("fields: must be a list of named fields")
        fields_cfg = {}
    for name, spec in fields_cfg.items():
        label = "fields.%s" % name
        if not re.fullmatch(r"[A-Za-z_]\w*", str(name)) or name in rules.BUILTINS:
            errors.append("%s: the name must be letters, digits and _, and not one of: %s" % (label, ", ".join(rules.BUILTINS)))
        if not isinstance(spec, dict) or "pattern" not in spec:
            errors.append("%s: needs a pattern" % label)
            continue
        try:
            re.compile(spec["pattern"])
        except re.error as e:
            errors.append("%s: the pattern is not a valid regular expression (%s)" % (label, e))
        if spec.get("type", "text") not in ("text", "number"):
            errors.append("%s: type must be text or number" % label)
        if spec.get("source", "document") not in ("document", "email", "subject"):
            errors.append("%s: source must be document, email or subject" % label)
        if spec.get("match", "first") not in ("first", "last"):
            errors.append("%s: match must be first or last" % label)

    allowed = PLACEHOLDERS | set(fields_cfg)

    templates = {}
    for category, tmpl in (raw.get("templates") or {}).items():
        if isinstance(tmpl, str):
            tmpl = {"body": tmpl}
        if not isinstance(tmpl, dict) or "body" not in tmpl:
            errors.append("templates.%s: needs a body" % category)
            continue
        _check_text("templates.%s.body" % category, tmpl["body"], allowed, errors)
        if tmpl.get("subject"):
            _check_text("templates.%s.subject" % category, tmpl["subject"], allowed, errors)
        templates[category] = tmpl

    rules_cfg = raw.get("rules") or []
    errors += rules.check_rules(rules_cfg, set(rules.BUILTINS) | set(fields_cfg))
    if isinstance(rules_cfg, list):
        for i, rule in enumerate(rules_cfg, 1):
            if isinstance(rule, dict) and rule.get("reply"):
                _check_text("rule %d (%s).reply" % (i, rule.get("name", "no name")), rule["reply"], allowed, errors)

    for key in _PATH_SETTINGS:
        p = str(settings[key])
        settings[key] = p if os.path.isabs(p) else os.path.join(BASE_DIR, p)

    cfg = {"settings": settings, "reply": reply, "templates": templates, "fields": fields_cfg, "rules": rules_cfg}
    return cfg, errors


def load(path: str = None) -> dict:

    """ Read and check the file. Raises ConfigError listing every problem found. """

    global _cfg, _mtime
    path = path or CONFIG_PATH
    try:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except FileNotFoundError:
        raise ConfigError("config file not found: %s" % path)
    except yaml.YAMLError as e:
        raise ConfigError("config.yaml is not valid YAML:\n%s" % e)

    if not isinstance(raw, dict):
        raise ConfigError("config.yaml must contain sections such as settings: and templates:")

    cfg, errors = _validate(raw)
    if errors:
        raise ConfigError("config.yaml has %d problem(s):\n  - %s" % (len(errors), "\n  - ".join(errors)))

    _cfg = cfg
    _mtime = os.path.getmtime(path)
    return cfg


def get() -> dict:
    return _cfg if _cfg is not None else load()


def setting(name: str):
    return get()["settings"][name]


def reload_if_changed() -> bool:

    """ Call this once per inbox check. Keeps the old config if the new file has a mistake. """

    global _failed_mtime
    try:
        mtime = os.path.getmtime(CONFIG_PATH)
    except OSError:
        return False
    if _mtime is not None and mtime == _mtime:
        return False
    if mtime == _failed_mtime:
        return False                            # same broken file, already reported
    try:
        load()
        print("config.yaml reloaded")
        return True
    except ConfigError as e:
        _failed_mtime = mtime
        print("config.yaml was NOT reloaded, still using the previous version.\n%s" % e)
        return False
