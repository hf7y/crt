import logging
import os
import time
import uuid

from zaxon_relay_db import get_conn

logger = logging.getLogger("zaxon_relay_inbox")

CLAIM_TTL_SECS = int(os.environ.get("ZAXON_INBOX_CLAIM_TTL_SECS", str(24 * 3600)))  # crt#129: how long a crashed agent's claim holds


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _claim_expiry_threshold() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - CLAIM_TTL_SECS))


def record_unclassified(message: str, reply_to_id, via: str = "text", for_agent=None) -> str:
    conn = get_conn()
    try:
        entry_id = uuid.uuid4().hex[:8]
        now = _iso_now()
        conn.execute(
            "INSERT INTO inbox (id, message, reply_to_id, received_at, via, for_agent) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (entry_id, message, reply_to_id, now, via, for_agent),
        )
        conn.commit()
    finally:
        conn.close()
    logger.warning(
        "unclassified inbound message recorded: id=%s reply_to=%s via=%s for_agent=%s",
        entry_id, reply_to_id, via, for_agent,
    )
    return entry_id


def claim(entry_id: str, agent: str, conn=None) -> bool:  # True if `agent` won, atomically
    owns_conn = conn is None
    conn = conn or get_conn()
    try:
        cur = conn.execute(
            "UPDATE inbox SET claimed_by=?, claimed_at=? WHERE id=? AND "
            "(claimed_by IS NULL OR claimed_by=? OR claimed_at<?)",
            (agent, _iso_now(), entry_id, agent, _claim_expiry_threshold()),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        if owns_conn:
            conn.close()


def fetch_inbox(conn=None, limit: int = 50, for_agent=None, include_claimed: bool = False) -> list:  # newest first; for_agent hides notes tagged/claimed elsewhere
    owns_conn = conn is None
    conn = conn or get_conn()
    try:
        if for_agent is None:
            rows = conn.execute(
                "SELECT id, message, reply_to_id, received_at, via, for_agent, "
                "claimed_by, claimed_at FROM inbox "
                "ORDER BY received_at DESC, rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
        else:
            where = "(for_agent IS NULL OR for_agent = ?)"
            params = [for_agent]
            if not include_claimed:
                where += " AND (claimed_by IS NULL OR claimed_by = ? OR claimed_at < ?)"
                params += [for_agent, _claim_expiry_threshold()]
            rows = conn.execute(
                "SELECT id, message, reply_to_id, received_at, via, for_agent, "
                f"claimed_by, claimed_at FROM inbox WHERE {where} "
                "ORDER BY received_at DESC, rowid DESC LIMIT ?",
                (*params, limit),
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
            "for_agent": r[5],
            "claimed_by": r[6],
            "claimed_at": r[7],
        }
        for r in rows
    ]
