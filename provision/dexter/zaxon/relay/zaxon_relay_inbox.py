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


def assign(for_agent: str, entry_id=None, conn=None):   # -> the id tagged, or None. entry_id omitted means the newest note nobody has tagged or claimed: a voice note that arrived untagged is what this exists for
    owns_conn = conn is None
    conn = conn or get_conn()
    try:
        if entry_id is None:
            row = conn.execute(
                "SELECT id FROM inbox WHERE for_agent IS NULL AND claimed_by IS NULL "
                "ORDER BY received_at DESC, rowid DESC LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            entry_id = row[0]
        cur = conn.execute(
            "UPDATE inbox SET for_agent=? WHERE id=? AND claimed_by IS NULL",   # a claimed note is being worked; readdressing it under the agent is not a correction
            (for_agent, entry_id),
        )
        conn.commit()
        return entry_id if cur.rowcount else None
    finally:
        if owns_conn:
            conn.close()


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
                "claimed_by, claimed_at, filed_issue FROM inbox "
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
                f"claimed_by, claimed_at, filed_issue FROM inbox WHERE {where} "
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
            "filed_issue": r[8],
        }
        for r in rows
    ]


def get_entry(entry_id: str, conn=None) -> dict:  # None if no such row -- callers check before reading a field
    owns_conn = conn is None
    conn = conn or get_conn()
    try:
        row = conn.execute(
            "SELECT id, message, reply_to_id, received_at, via, for_agent, "
            "claimed_by, claimed_at, filed_issue FROM inbox WHERE id=?",
            (entry_id,),
        ).fetchone()
    finally:
        if owns_conn:
            conn.close()
    if row is None:
        return None
    return {
        "id": row[0],
        "message": row[1],
        "reply_to_id": row[2],
        "received_at": row[3],
        "via": row[4],
        "for_agent": row[5],
        "claimed_by": row[6],
        "claimed_at": row[7],
        "filed_issue": row[8],
    }


def set_filed_issue(entry_id: str, issue_ref: str, conn=None) -> None:
    owns_conn = conn is None
    conn = conn or get_conn()
    try:
        conn.execute("UPDATE inbox SET filed_issue=? WHERE id=?", (issue_ref, entry_id))
        conn.commit()
    finally:
        if owns_conn:
            conn.close()


def unfiled(conn=None) -> list:  # crt#154: tagged notes a crashed/restarted watcher never got to file
    owns_conn = conn is None
    conn = conn or get_conn()
    try:
        rows = conn.execute(
            "SELECT id, for_agent FROM inbox WHERE for_agent IS NOT NULL AND filed_issue IS NULL"
        ).fetchall()
    finally:
        if owns_conn:
            conn.close()
    return [{"id": r[0], "for_agent": r[1]} for r in rows]
