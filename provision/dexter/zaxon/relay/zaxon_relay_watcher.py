#!/usr/bin/env python3
"""Tails hermes-agent's agent.log for inbound WhatsApp replies that quote a
Zaxon relay message, and resolves the matching ticket.

Reads only hermes-agent's log file, never its process or source -- survives
`hermes update`; a changed log format just stops matching (fails closed).

Restart-safe: persists a byte-offset checkpoint after every line, so a
crash/redeploy/systemd bounce never silently skips a reply -- replaying
already-seen lines is always safe, since resolve_reply() only touches rows
still 'pending'.

A voice note that failed to transcribe is NOT resolved as a reply: its
audio is retained instead and the ticket stays pending (retain_audio).

Also the only long-running loop the relay has, so it carries crt#67's
staleness sweep too (STALE_SWEEP_EVERY_TICKS): otherwise a queued question
only gets promoted next time some agent happens to poll, which may be never.
"""
import logging
import os
import re
import shutil
import time
from pathlib import Path

from zaxon_relay_db import get_conn
from zaxon_relay_filer import file_issue, file_pending
from zaxon_relay_inbox import assign, record_unclassified

logger = logging.getLogger("zaxon_relay_watcher")
from zaxon_relay_queue import sweep_and_promote

LOG_PATH = Path.home() / ".hermes" / "logs" / "agent.log"
OFFSET_PATH = Path.home() / ".hermes" / "zaxon_relay" / "watcher.offset"
AUDIO_DIR = Path.home() / ".hermes" / "zaxon_relay" / "audio"

STALE_SWEEP_EVERY_TICKS = 60  # ~30s at the 0.5s idle sleep below

LINE_RE = re.compile(
    r"inbound message: platform=whatsapp .*?msg='(?P<msg>.*)' "
    r"reply_to_id=(?P<reply_id>\S+) reply_to_text='"
)

# What the gateway substitutes for a voice note it could not transcribe. The
# audio it names is real, and on 2026-08-17 and 2026-08-19 it was swept out
# of cache/audio before anyone read the message -- so the reply was lost
# twice over, once by whisper being dead and once by nobody keeping the file.
STT_FAILED_RE = re.compile(
    r"\[voice message could not be transcribed automatically; "
    r"the audio is available at: (?P<path>[^\]]+)\]"
)

# The gateway transcribes immediately before dispatching the message, so a
# transcription line means the NEXT inbound message is a voice note's text.
# The failure line above is self-identifying; only the SUCCESS path needs
# this, and the success path has never once run here -- whisper was dead
# 2026-08-02 to 2026-08-25. Confirm the pattern against the first real voice
# note rather than trusting it: a wrong guess mislabels `via` and nothing more.
TRANSCRIBED_RE = re.compile(r"transcription", re.IGNORECASE)

FOR_AGENT_TAG_RE = re.compile(r"^(?P<repo>[A-Za-z][A-Za-z0-9_-]*):\s+(?P<body>.+)$", re.DOTALL)  # crt#130: "repo: message" addresses a note


RETAG_RE = re.compile(   # crt#154: "tag realisateur" readdresses the last untagged note. Checked BEFORE FOR_AGENT_TAG_RE, which would otherwise read "tag: realisateur" as repo "tag"
    r"^tag:?\s+(?:(?P<entry>[0-9a-f]{8})\s+)?(?P<repo>[A-Za-z][A-Za-z0-9_-]*)\s*$",
    re.IGNORECASE,
)


def _file_safely(entry_id) -> None:   # crt#154: a filing failure (gh/defere down, no network) must never take down the only long-running loop this relay has
    if entry_id is None:
        return
    try:
        file_issue(entry_id)
    except Exception:
        logger.exception("failed to file pointer issue for inbox %s", entry_id)


def _retag(msg: str) -> bool:   # True when msg WAS a retag and landed; a retag that finds nothing falls through and is recorded, so a mistyped one is never silently eaten
    m = RETAG_RE.match(msg.strip())
    if not m:
        return False
    tagged = assign(m.group("repo"), m.group("entry"))
    if tagged is None:
        return False
    logger.warning("retagged inbox entry %s for %s", tagged, m.group("repo"))
    _file_safely(tagged)   # a corrected tag gets its own pointer issue, and moves it off a stale one
    return True


def _split_for_agent(msg: str):  # (for_agent, body); for_agent is None when untagged
    m = FOR_AGENT_TAG_RE.match(msg)
    if not m:
        return None, msg
    return m.group("repo"), m.group("body")


def resolve_reply(reply_id: str, msg: str, via: str = "text") -> bool:
    """True if `reply_id` owned a pending ticket that got resolved."""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id FROM tickets WHERE wa_message_id=? AND status='pending'",
            (reply_id,),
        ).fetchone()
        if row is None:
            return False
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        conn.execute(
            "UPDATE tickets SET status='answered', answer=?, answered_at=?, via=? "
            "WHERE id=?",
            (msg, now, via, row[0]),
        )
        conn.commit()
        sweep_and_promote(conn)
        return True
    finally:
        conn.close()


def retain_audio(reply_id: str, audio_path: str) -> bool:
    """Not an answer -- the ticket stays pending -- but the audio is copied
    out of the gateway's cache (which gets swept) so zaxon-retranscribe can
    use it later. True when this line was a failed transcription against an
    open ticket, i.e. the caller must not treat it as a reply."""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id FROM tickets WHERE wa_message_id=? AND status='pending'",
            (reply_id,),
        ).fetchone()
        if row is None:
            return False
        ticket_id = row[0]
        src = Path(audio_path)
        try:
            AUDIO_DIR.mkdir(parents=True, exist_ok=True)
            dest = AUDIO_DIR / f"{ticket_id}{src.suffix or '.ogg'}"
            shutil.copy2(src, dest)
        except OSError:
            # Already swept, or unreadable. Still not an answer: leaving the
            # ticket pending is the honest state, and inventing one out of a
            # message that only says "could not hear you" would be worse.
            return True
        conn.execute(
            "UPDATE tickets SET audio_path=? WHERE id=?", (str(dest), ticket_id)
        )
        conn.commit()
        return True
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


def _handle_message(reply_id: str, msg: str, via: str) -> None:
    handled = False
    if reply_id != "None":
        failed = STT_FAILED_RE.search(msg)
        if failed:
            handled = retain_audio(reply_id, failed.group("path").strip())
        else:
            handled = resolve_reply(reply_id, msg, via)
    if not handled:
        handled = _retag(msg)
    if not handled:
        for_agent, body = _split_for_agent(msg)
        entry_id = record_unclassified(
            body, None if reply_id == "None" else reply_id, via, for_agent=for_agent
        )
        if for_agent is not None:
            _file_safely(entry_id)   # crt#154: tagged on arrival, e.g. "realisateur: ..."


def main() -> None:
    while not LOG_PATH.exists():
        time.sleep(2)

    with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        start = _load_checkpoint(size)
        f.seek(start)

        idle_ticks = 0
        voice_hint = False
        while True:
            line = f.readline()
            if not line:
                idle_ticks += 1
                if idle_ticks >= STALE_SWEEP_EVERY_TICKS:
                    idle_ticks = 0
                    conn = get_conn()
                    try:
                        sweep_and_promote(conn)
                        try:
                            file_pending(conn)   # crt#154: catches a filing that failed transiently (gh/defere down) rather than losing it
                        except Exception:
                            logger.exception("file_pending sweep failed")
                    finally:
                        conn.close()
                time.sleep(0.5)
                continue
            idle_ticks = 0

            m = LINE_RE.search(line)
            if m:
                via = "voice" if voice_hint else "text"
                _handle_message(m.group("reply_id"), m.group("msg"), via)
                voice_hint = False
            elif TRANSCRIBED_RE.search(line):
                voice_hint = True

            # Checkpoint after every line -- cheap at this log volume, and
            # the whole point is to never lose a gap between checkpoints.
            _save_checkpoint(f.tell())


if __name__ == "__main__":
    main()
