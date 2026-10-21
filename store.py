import sqlite3
from datetime import datetime, timedelta

DB_PATH = "ingestion.db"


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _execute(sql, params=()):
    conn = _connect()
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _query(sql, params=()):
    conn = _connect()
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def _now():
    return datetime.now().isoformat(timespec="seconds")


def init_db():

    """ Create the tables if they do not exist yet. """

    conn = _connect()
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS emails (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            gmail_msg_id   TEXT NOT NULL UNIQUE,
            sender         TEXT,
            subject        TEXT,
            mail_date      TEXT,
            received_at    TEXT NOT NULL,
            category       TEXT,
            reply_status   TEXT NOT NULL DEFAULT 'not_needed',
            reply_sent_at  TEXT,
            reply_msg_id   TEXT
        );

        CREATE TABLE IF NOT EXISTS documents (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            email_id       INTEGER REFERENCES emails(id),
            file_name      TEXT NOT NULL,
            file_path      TEXT NOT NULL,
            file_hash      TEXT,
            file_type      TEXT,
            status         TEXT NOT NULL,
            error_message  TEXT,
            json_path      TEXT,
            created_at     TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS blocked_senders (
            address        TEXT PRIMARY KEY
        );
        """)
        conn.commit()
    finally:
        conn.close()


# ---------- emails ----------

def email_done(gmail_id: str) -> bool:

    """ True if this mail was fully handled before (it has a category). """

    rows = _query("SELECT 1 FROM emails WHERE gmail_msg_id = ? AND category IS NOT NULL", (gmail_id,))
    return len(rows) > 0


def start_email(mail: dict) -> int:

    """ Create the row for a mail. If an unfinished row exists (crash), reuse it and clear its documents. """

    rows = _query("SELECT id FROM emails WHERE gmail_msg_id = ?", (mail["id"],))
    if rows:
        email_id = rows[0]["id"]
        _execute("DELETE FROM documents WHERE email_id = ?", (email_id,))
        return email_id

    return _execute(
        "INSERT INTO emails (gmail_msg_id, sender, subject, mail_date, received_at) VALUES (?, ?, ?, ?, ?)",
        (mail["id"], mail["sender_email"], mail["subject"], mail["date"], _now()),
    )


def finish_email(email_id: int, category: str, reply_status: str = "not_needed"):
    _execute("UPDATE emails SET category = ?, reply_status = ? WHERE id = ?", (category, reply_status, email_id))


def set_reply(email_id: int, status: str, reply_msg_id: str = None):
    sent_at = _now() if status == "sent" else None
    _execute(
        "UPDATE emails SET reply_status = ?, reply_sent_at = ?, reply_msg_id = ? WHERE id = ?",
        (status, sent_at, reply_msg_id, email_id),
    )


def replies_last_day(sender: str) -> int:
    cutoff = (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds")
    rows = _query(
        "SELECT COUNT(*) AS n FROM emails WHERE sender = ? AND reply_status = 'sent' AND reply_sent_at >= ?",
        (sender, cutoff),
    )
    return rows[0]["n"]


def replied_recently(sender: str, category: str, minutes: int = 60) -> bool:
    cutoff = (datetime.now() - timedelta(minutes=minutes)).isoformat(timespec="seconds")
    rows = _query(
        "SELECT 1 FROM emails WHERE sender = ? AND category = ? AND reply_status = 'sent' AND reply_sent_at >= ?",
        (sender, category, cutoff),
    )
    return len(rows) > 0


# ---------- documents ----------

def add_document(email_id, file_name, file_path, file_hash, file_type, status, error=None, json_path=None) -> int:
    return _execute(
        "INSERT INTO documents (email_id, file_name, file_path, file_hash, file_type, status, error_message, json_path, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (email_id, file_name, file_path, file_hash, file_type, status, error, json_path, _now()),
    )


def has_hash(file_hash: str) -> bool:

    """ True if a file with the same content was already processed successfully. """

    rows = _query("SELECT 1 FROM documents WHERE file_hash = ? AND status = 'completed'", (file_hash,))
    return len(rows) > 0


# ---------- blocklist ----------

def is_blocked(address: str) -> bool:
    return len(_query("SELECT 1 FROM blocked_senders WHERE address = ?", (address.lower(),))) > 0


def block_sender(address: str):
    _execute("INSERT OR IGNORE INTO blocked_senders (address) VALUES (?)", (address.lower(),))