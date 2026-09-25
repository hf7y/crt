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

A document-attached audio (crt#304) gets no transcription line at all from
the gateway -- it logs a bare '[document received]' placeholder instead.
That placeholder is NEVER resolved as a ticket's answer either: it is
transcribed here, from whatever the gateway most recently cached, and
lands as an inbox memo (via=voice) instead.

A plain follow-up naming a repo ("that's for apms", crt#305) retags the
newest untagged note the same as "tag apms" -- Zach cannot tag a note as
he speaks it, only after.

An untagged reply that quotes nothing is matched against the one pending
ticket, if exactly one exists, falling back to a lone stale one if none is
pending (resolve_unthreaded_reply, crt#244) -- the only way a reply can
quote nothing is that its question never reached the phone to be quoted.

Also the only long-running loop the relay has, so it carries crt#67's
staleness sweep too (STALE_SWEEP_EVERY_TICKS): otherwise a queued question
only gets promoted next time some agent happens to poll, which may be never.
"""
import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from zaxon_relay_db import get_conn
from zaxon_relay_inbox import assign, record_unclassified

logger = logging.getLogger("zaxon_relay_watcher")
from zaxon_relay_queue import sweep_and_promote
from zaxon_relay_queue import GATEWAY_CACHE_AUDIO_DIR as DOCUMENT_CACHE_DIR
from zaxon_relay_queue import _transcribe
from zaxon_relay_queue import start_netns_guard_thread

LOG_PATH = Path.home() / ".hermes" / "logs" / "agent.log"
OFFSET_PATH = Path.home() / ".hermes" / "zaxon_relay" / "watcher.offset"
AUDIO_DIR = Path.home() / ".hermes" / "zaxon_relay" / "audio"

DOCUMENT_TRANSCRIBE_WINDOW_SECS = 120  # margin for the gateway to finish writing its cache file before this placeholder's log line lands

STALE_SWEEP_EVERY_TICKS = 60  # ~30s at the 0.5s idle sleep below

LINE_RE = re.compile(
    r"inbound message: platform=whatsapp .*?msg='(?P<msg>.*)' "
    r"reply_to_id=(?P<reply_id>\S+) reply_to_text='"
)

# What the gateway substitutes for a voice note it could not transcribe.
STT_FAILED_RE = re.compile(
    r"\[voice message could not be transcribed automatically; "
    r"the audio is available at: (?P<path>[^\]]+)\]"
)

# What the gateway logs for a document-attached audio (crt#304): no
# transcription attempt at all, unlike a voice note, and no path either.
DOCUMENT_PLACEHOLDER_RE = re.compile(r"^\[document received\]$")

# The gateway transcribes immediately before dispatching, so this line always
# precedes the voice note's own inbound line -- see _process_line.
TRANSCRIBED_RE = re.compile(r"transcription", re.IGNORECASE)

FOR_AGENT_TAG_RE = re.compile(r"^(?P<repo>[A-Za-z][A-Za-z0-9_-]*):\s+(?P<body>.+)$", re.DOTALL)  # crt#130: "repo: message" addresses a note


RETAG_RE = re.compile(   # crt#154: "tag realisateur" readdresses the last untagged note. Checked BEFORE FOR_AGENT_TAG_RE, which would otherwise read "tag: realisateur" as repo "tag"
    r"^tag:?\s+(?:(?P<entry>[0-9a-f]{8})\s+)?(?P<repo>[A-Za-z][A-Za-z0-9_-]*)\s*$",
    re.IGNORECASE,
)

FOLLOWUP_TAG_RE = re.compile(   # crt#305: "that's for apms" -- Zach can't tag a voice note as he speaks it, so a plain follow-up naming a repo retags the newest untagged one, same as "tag apms" but without the trigger word
    r"\bfor\s+(?P<repo>[A-Za-z][A-Za-z0-9_-]*)[.!]?\s*$",
    re.IGNORECASE,
)


def _retag(msg: str) -> bool:   # True when msg WAS a retag and landed; a retag that finds nothing falls through and is recorded, so a mistyped one is never silently eaten
    m = RETAG_RE.match(msg.strip())
    if not m:
        return False
    tagged = assign(m.group("repo"), m.group("entry"))
    if tagged is None:
        return False
    logger.warning("retagged inbox entry %s for %s", tagged, m.group("repo"))
    return True


def _followup_tag(msg: str) -> bool:   # True when msg WAS a follow-up tag and landed; same fall-through-if-nothing-to-tag contract as _retag
    m = FOLLOWUP_TAG_RE.search(msg.strip())
    if not m:
        return False
    tagged = assign(m.group("repo"))
    if tagged is None:
        return False
    logger.warning("follow-up tagged inbox entry %s for %s", tagged, m.group("repo"))
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


def resolve_unthreaded_reply(msg: str, via: str = "text") -> bool:
    """Safe to guess only when exactly one ticket is pending: the
    per-from_agent slot (crt#230) already keeps that number small, and at
    exactly one there is nothing else it could be.

    Falls back to a lone 'stale' ticket when none is pending (crt#244): a
    question that never reached the phone in time to be quoted is the same
    reason it may also have aged out before Zach could reply to it -- the
    reply is not late, the delivery was. Only when nothing is pending, so
    this never steals a reply that plainly belongs to the current question."""
    conn = get_conn()
    try:
        rows = conn.execute("SELECT id FROM tickets WHERE status='pending'").fetchall()
        if len(rows) != 1:
            if rows:
                return False
            rows = conn.execute("SELECT id FROM tickets WHERE status='stale'").fetchall()
            if len(rows) != 1:
                return False
        ticket_id = rows[0][0]
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        conn.execute(
            "UPDATE tickets SET status='answered', answer=?, answered_at=?, via=? "
            "WHERE id=?",
            (msg, now, via, ticket_id),
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


def _transcribe_untranscribed_document() -> str:
    """Best-effort transcription of whatever the gateway most recently
    cached, for a '[document received]' placeholder (crt#304). Never
    raises and returns '' on any failure -- a lost transcription must
    still land as an inbox entry, just with the placeholder text instead."""
    try:
        if not DOCUMENT_CACHE_DIR.is_dir():
            return ""
        threshold = time.time() - DOCUMENT_TRANSCRIBE_WINDOW_SECS
        candidates = sorted(
            (p for p in DOCUMENT_CACHE_DIR.iterdir() if p.is_file() and p.stat().st_mtime > threshold),
            key=lambda p: p.stat().st_mtime,
        )
        if not candidates:
            return ""
        return _transcribe(str(candidates[-1])) or ""
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return ""


def _handle_message(reply_id: str, msg: str, via: str) -> None:
    if DOCUMENT_PLACEHOLDER_RE.match(msg.strip()):
        # crt#304: never resolve a ticket with this placeholder -- transcribe
        # it ourselves and land it as a memo instead, exactly like any other
        # untagged voice note.
        text = _transcribe_untranscribed_document() or msg
        record_unclassified(text, None if reply_id == "None" else reply_id, "voice")
        return
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
        handled = _followup_tag(msg)
    for_agent, body = _split_for_agent(msg)
    if (
        not handled
        and reply_id == "None"
        and for_agent is None
        and not RETAG_RE.match(msg.strip())
        and not FOLLOWUP_TAG_RE.search(msg.strip())
    ):
        # A retag/follow-up tag that named nothing to retag (bad repo, no
        # untagged note) must still land in the inbox, not get swallowed as
        # a ticket's answer just because it also happens to be the lone
        # pending one.
        handled = resolve_unthreaded_reply(msg, via)
    if not handled:
        record_unclassified(
            body, None if reply_id == "None" else reply_id, via, for_agent=for_agent
        )


def _process_line(line: str, voice_hint: bool) -> bool:
    """Advance the voice-hint state machine by one tailed line, dispatching
    a matched inbound line to _handle_message. Returns the voice_hint to
    carry into the next line: a TRANSCRIBED_RE line sets it, the next
    LINE_RE match consumes it (as via="voice") and clears it, and any other
    line leaves it unchanged."""
    m = LINE_RE.search(line)
    if m:
        via = "voice" if voice_hint else "text"
        _handle_message(m.group("reply_id"), m.group("msg"), via)
        return False
    if TRANSCRIBED_RE.search(line):
        return True
    return voice_hint


def main() -> None:
    start_netns_guard_thread()  # crt#322: exit if stranded in a dead namespace

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
                    finally:
                        conn.close()
                time.sleep(0.5)
                continue
            idle_ticks = 0

            voice_hint = _process_line(line, voice_hint)
            _save_checkpoint(f.tell())


if __name__ == "__main__":
    main()
