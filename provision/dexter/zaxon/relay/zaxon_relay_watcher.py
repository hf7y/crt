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

A voice note that failed to transcribe is NOT resolved as a reply: its
audio is retained instead and the ticket stays pending (retain_audio).

Also the only long-running loop the relay has, so it carries crt#67's
staleness sweep too (STALE_SWEEP_EVERY_TICKS): otherwise a queued question
only gets promoted next time some agent happens to poll, which may be never.
"""
import os
import re
import shutil
import time
from pathlib import Path

from zaxon_relay_db import get_conn
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


def resolve_reply(reply_id: str, msg: str, via: str = "text") -> None:
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
            "UPDATE tickets SET status='answered', answer=?, answered_at=?, via=? "
            "WHERE id=?",
            (msg, now, via, row[0]),
        )
        conn.commit()
        sweep_and_promote(conn)
    finally:
        conn.close()


def retain_audio(reply_id: str, audio_path: str) -> bool:
    """A voice note that would not transcribe is not an answer -- the ticket
    stays pending. But the audio it names IS the answer, so copy it out of
    the gateway's cache, which gets swept, into the relay's own directory,
    which does not. zaxon-retranscribe turns it into an answer once whisper
    is healthy again.

    Returns True when this line was a failed transcription against an open
    ticket, i.e. the caller must not treat it as a reply."""
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
                    finally:
                        conn.close()
                time.sleep(0.5)
                continue
            idle_ticks = 0

            m = LINE_RE.search(line)
            if m:
                reply_id = m.group("reply_id")
                if reply_id != "None":
                    msg = m.group("msg")
                    failed = STT_FAILED_RE.search(msg)
                    if failed:
                        retain_audio(reply_id, failed.group("path").strip())
                    else:
                        resolve_reply(reply_id, msg, "voice" if voice_hint else "text")
                voice_hint = False
            elif TRANSCRIBED_RE.search(line):
                voice_hint = True

            # Checkpoint after every line -- cheap at this log volume, and
            # the whole point is to never lose a gap between checkpoints.
            _save_checkpoint(f.tell())


if __name__ == "__main__":
    main()
