"""Single-slot question queue on top of the tickets table (crt#67).

Zach's complaint: with `ask_zach` sending every question straight to
WhatsApp, three questions in flight look like three separate pings on his
phone -- the spam the relay exists to avoid. The fix is a queue with one
question visible at a time:

- **One open question.** A new question is inserted as 'queued'. It is
  only sent (promoted to 'pending') once no other ticket is 'pending'.
- **Staleness.** A 'pending' ticket older than QUESTION_TTL_SECS is marked
  'stale' so an ignored question can't wedge the queue forever; the next
  'queued' ticket is then promoted.
- **Style, enforced by refusing rather than truncating.** See
  validate_question(). A poll (options=[...]) is preferred over free text.

sweep_and_promote() is the only place a ticket moves 'queued' -> 'pending',
and it is safe to call from anywhere that holds a connection (ask_zach,
check_zach_reply, and the watcher's idle/reply-resolved loop) -- it is a
plain read-then-maybe-write against sqlite, not a background thread, so
calling it more often only makes promotion happen sooner.
"""
import calendar
import json
import os
import subprocess
import time
from pathlib import Path

MAX_QUESTION_CHARS = 140
QUESTION_TTL_SECS = int(os.environ.get("ZAXON_QUESTION_TTL_SECS", "3600"))

HERMES_BIN = str(Path.home() / ".hermes" / "hermes-agent" / ".venv" / "bin" / "hermes")


def validate_question(question: str) -> None:
    """Refuses (raises) rather than truncating -- a caller that can't fit
    the question in MAX_QUESTION_CHARS hasn't decided what it's asking."""
    if len(question) >= MAX_QUESTION_CHARS:
        raise ValueError(
            f"question is {len(question)} chars; must be under {MAX_QUESTION_CHARS} "
            "(refused, not truncated)"
        )


def format_message(from_agent: str, ticket_id: str, question: str, options) -> str:
    """No boilerplate headers -- screen real estate on a phone is the
    scarce resource here, not clarity for a machine reader."""
    lines = [f"\U0001F500 [{from_agent}] {question}"]
    if options:
        lines += [f"{i}. {opt}" for i, opt in enumerate(options, start=1)]
    lines.append(f"(#{ticket_id})")
    return "\n".join(lines)


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _epoch(iso_ts: str) -> float:
    return calendar.timegm(time.strptime(iso_ts, "%Y-%m-%dT%H:%M:%SZ"))


def _default_sender(text: str) -> dict:
    proc = subprocess.run(
        [HERMES_BIN, "send", "--to", "whatsapp:Zach", text, "--json"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return json.loads(proc.stdout or "{}")


def deliver(conn, ticket_id: str, from_agent: str, question: str, options, sender=None) -> str:
    """Sends one ticket over WhatsApp and updates its row in place. Returns
    the resulting status ('pending' or 'failed'). `sender` is injectable
    for tests; production callers omit it and get the real hermes send."""
    send = sender or _default_sender
    text = format_message(from_agent, ticket_id, question, options)
    try:
        payload = send(text)
    except Exception as e:  # noqa: BLE001 -- surfaced on the ticket, not swallowed
        conn.execute("UPDATE tickets SET status='failed', answer=? WHERE id=?", (str(e), ticket_id))
        conn.commit()
        return "failed"

    if not payload.get("success"):
        err = payload.get("error", "unknown send failure")
        conn.execute("UPDATE tickets SET status='failed', answer=? WHERE id=?", (err, ticket_id))
        conn.commit()
        return "failed"

    conn.execute(
        "UPDATE tickets SET status='pending', wa_message_id=? WHERE id=?",
        (payload.get("message_id"), ticket_id),
    )
    conn.commit()
    return "pending"


def sweep_and_promote(conn, sender=None) -> None:
    """Expires an overdue 'pending' ticket, then promotes the oldest
    'queued' ticket into the freed slot. No-op if the slot is occupied by
    a still-fresh 'pending' ticket, or nothing is queued."""
    pending = conn.execute(
        "SELECT id, created_at FROM tickets WHERE status='pending' LIMIT 1"
    ).fetchone()
    if pending is not None:
        ticket_id, created_at = pending
        if time.time() - _epoch(created_at) <= QUESTION_TTL_SECS:
            return
        conn.execute("UPDATE tickets SET status='stale' WHERE id=?", (ticket_id,))
        conn.commit()

    nxt = conn.execute(
        "SELECT id, from_agent, question, options FROM tickets "
        "WHERE status='queued' ORDER BY created_at LIMIT 1"
    ).fetchone()
    if nxt is None:
        return
    ticket_id, from_agent, question, options_json = nxt
    options = json.loads(options_json) if options_json else None
    deliver(conn, ticket_id, from_agent, question, options, sender=sender)
