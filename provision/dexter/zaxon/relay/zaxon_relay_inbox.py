import logging
import time
import uuid

from zaxon_relay_db import get_conn

logger = logging.getLogger("zaxon_relay_inbox")


def record_unclassified(message: str, reply_to_id, via: str = "text") -> str:
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
    owns_conn = conn is None
    conn = conn or get_conn()
    try:
        # rowid DESC tiebreaks same-second entries by insertion order.
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
