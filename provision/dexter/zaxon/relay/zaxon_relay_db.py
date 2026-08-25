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
    answered_at TEXT
)
"""


def get_conn() -> sqlite3.Connection:
    """Also migrates a pre-crt#67 db: CREATE TABLE IF NOT EXISTS won't add
    'options' to a tickets table that predates it."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.execute(SCHEMA)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(tickets)")}
    if "options" not in cols:
        conn.execute("ALTER TABLE tickets ADD COLUMN options TEXT")
    conn.commit()
    return conn
