"""Inbound WhatsApp messages that resolve to no pending ticket -- an
unsolicited note from Zach, or a reply that arrives after its ticket has
already gone stale. Previously dropped in place (crt#87): resolve_reply()
and retain_audio() both return silently when no pending ticket owns the
reply, and a reply_to_id of 'None' (no ticket at all) was never even
looked up. record_unclassified() is the one path that writes such a
message down; fetch_inbox() is the one path that reads it back.

No content-based inference of intent lives here -- a message is stored
verbatim, never parsed into a category. Unclassified is a valid, visible
state until some consumer (an MCP tool, a script) decides what it means.
"""
import logging
import time
import uuid

from zaxon_relay_db import get_conn

logger = logging.getLogger("zaxon_relay_inbox")


def record_unclassified(message: str, reply_to_id, via: str = "text") -> str:
    """Records an inbound message that matched no pending ticket, and logs
    the event -- a silent `return` here is exactly the failure mode this
    module exists to close."""
    conn = get_conn()
    try:
        entry_id = uuid.uuid4().hex[:8]
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        conn.execute(
            "INSERT INTO inbox (id, message, reply_to_id, received_at, via) "
            "VALUES (?, ?, ?, ?, ?)",
            (entry_id, message, reply_to_id, now, via),
        )
        conn.commit()
    finally:
        conn.close()
    logger.warning(
        "unclassified inbound message recorded: id=%s reply_to=%s via=%s",
        entry_id, reply_to_id, via,
    )
    return entry_id


def fetch_inbox(conn=None, limit: int = 50) -> list:
    """Every unclassified inbound message, newest first, capped at `limit`.
    Read-only and non-destructive: any number of consumers can each call
    this and see the same entries -- nothing here decides one has been
    handled, so that judgment stays with whatever reads it."""
    owns_conn = conn is None
    conn = conn or get_conn()
    try:
        # rowid DESC breaks ties within the same received_at second in
        # insertion order -- the timestamp alone is too coarse to tell two
        # messages landing in the same second apart.
        rows = conn.execute(
            "SELECT id, message, reply_to_id, received_at, via FROM inbox "
            "ORDER BY received_at DESC, rowid DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        if owns_conn:
            conn.close()
    return [
        {
            "id": r[0],
            "message": r[1],
            "reply_to_id": r[2],
            "received_at": r[3],
            "via": r[4],
        }
        for r in rows
    ]
