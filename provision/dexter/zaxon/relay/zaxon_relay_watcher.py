#!/usr/bin/env python3
"""Tails hermes-agent's agent.log for inbound WhatsApp replies that quote a
Zaxon relay message, and resolves the matching ticket.

Deliberately does not touch hermes-agent's own process or source -- it only
reads the log file hermes-agent already writes. Safe against `hermes
update`; if the log line format ever changes, this just stops matching
(fails closed, not loudly).

Restart-safe: persists a byte-offset checkpoint after every line so a
watcher restart (crash, redeploy, systemd bounce) can never silently skip a
reply that landed in the gap. resolve_reply() only updates rows still
'pending', so replaying already-seen lines on top of a stale/missing
checkpoint is always safe -- prefer reprocessing over ever risking SEEK_END.
"""
import os
import re
import time
from pathlib import Path

from zaxon_relay_db import get_conn

LOG_PATH = Path.home() / ".hermes" / "logs" / "agent.log"
OFFSET_PATH = Path.home() / ".hermes" / "zaxon_relay" / "watcher.offset"

LINE_RE = re.compile(
    r"inbound message: platform=whatsapp .*?msg='(?P<msg>.*)' "
    r"reply_to_id=(?P<reply_id>\S+) reply_to_text='"
)


def resolve_reply(reply_id: str, msg: str) -> None:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id FROM tickets WHERE wa_message_id=? AND status='pending'",
            (reply_id,),
        ).fetchone()
        if row is None:
            return
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        conn.execute(
            "UPDATE tickets SET status='answered', answer=?, answered_at=? WHERE id=?",
            (msg, now, row[0]),
        )
        conn.commit()
    finally:
        conn.close()


def _load_checkpoint(file_size: int) -> int:
    """Return the byte offset to resume from. 0 on first-ever run or if the
    saved checkpoint is past the current file size (log was truncated)."""
    try:
        offset = int(OFFSET_PATH.read_text().strip())
    except (FileNotFoundError, ValueError):
        return 0
    if offset > file_size:
        return 0  # log was truncated/rotated -- reprocess rather than skip
    return offset


def _save_checkpoint(offset: int) -> None:
    OFFSET_PATH.write_text(str(offset))


def main() -> None:
    while not LOG_PATH.exists():
        time.sleep(2)

    with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        start = _load_checkpoint(size)
        f.seek(start)

        while True:
            line = f.readline()
            if not line:
                time.sleep(0.5)
                continue

            m = LINE_RE.search(line)
            if m:
                reply_id = m.group("reply_id")
                if reply_id != "None":
                    resolve_reply(reply_id, m.group("msg"))

            # Checkpoint after every line -- cheap at this log volume, and
            # the whole point is to never lose a gap between checkpoints.
            _save_checkpoint(f.tell())


if __name__ == "__main__":
    main()
