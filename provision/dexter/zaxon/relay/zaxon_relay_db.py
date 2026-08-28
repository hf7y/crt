"""Shared sqlite ticket store for the Zaxon relay MCP tool."""
from pathlib import Path
import sqlite3

DB_PATH = Path.home() / ".hermes" / "zaxon_relay" / "tickets.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id TEXT PRIMARY KEY,
    from_agent TEXT NOT NULL,
    question TEXT NOT NULL,
    wa_message_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    answer TEXT,
    created_at TEXT NOT NULL,
    answered_at TEXT,
    chat_id TEXT,
    via TEXT,
    audio_path TEXT
)
"""

# An inbound WhatsApp message that matched no pending ticket (crt#87) --
# unsolicited, or a reply that arrived after its ticket went stale. Kept
# separate from tickets: nothing here ever expects a reply of its own.
INBOX_SCHEMA = """
CREATE TABLE IF NOT EXISTS inbox (
    id TEXT PRIMARY KEY,
    message TEXT NOT NULL,
    reply_to_id TEXT,
    received_at TEXT NOT NULL,
    via TEXT
)
"""


def get_conn() -> sqlite3.Connection:
    """Also migrates an older db in place: CREATE TABLE IF NOT EXISTS won't
    add a column to a tickets table that predates it, and tickets.db on
    dexter is live state that is never recreated from the repo."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.execute(SCHEMA)
    conn.execute(INBOX_SCHEMA)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(tickets)")}
    for col in ("options", "chat_id", "via", "audio_path"):
        if col not in cols:
            conn.execute(f"ALTER TABLE tickets ADD COLUMN {col} TEXT")
    conn.commit()
    return conn
