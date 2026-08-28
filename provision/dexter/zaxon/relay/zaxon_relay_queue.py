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
  validate_message(), which measures the RENDERED message -- bold repo tag
  and option lines included -- not the question alone. A poll
  (options=[...]) is preferred over free text.

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


def validate_repo(repo: str) -> None:
    """The tag is a repo name, not a free-form agent nickname (Zach
    2026-08-25). A space is the cheap tell that someone typed a sentence;
    enumerating the real repos here would only rot."""
    if not repo or not repo.strip():
        raise ValueError("repo is required -- it is the bold tag Zach reads first")
    if " " in repo:
        raise ValueError(f"repo {repo!r} contains a space; a repo name does not")
    if repo == "agent":
        raise ValueError(
            "'agent' is the old default, not a repo -- name the repo you are "
            "working in, it is the bold tag Zach reads first"
        )


def format_message(repo: str, question: str, options) -> str:
    """The bold repo name leads and nothing else is added. The ticket id
    used to trail every message, but the watcher matches replies on the
    WhatsApp quote (reply_to_id), never on that text -- so it was eleven
    characters of a 140-character screen spent on nobody."""
    lines = [f"*{repo}* {question}"]
    if options:
        lines += [f"{i}. {opt}" for i, opt in enumerate(options, start=1)]
    return "\n".join(lines)


def validate_message(repo: str, question: str, options=None) -> str:
    """Measures what actually lands on the phone -- repo tag and option
    lines included -- because 140 is inclusive (Zach 2026-08-25). Measuring
    the question alone let the rendered message run ~19 chars over.

    Refuses rather than truncating: a caller who can't fit it hasn't
    decided what it's asking. Returns the rendered text so callers don't
    render twice."""
    validate_repo(repo)
    text = format_message(repo, question, options)
    if len(text) > MAX_QUESTION_CHARS:
        raise ValueError(
            f"rendered message is {len(text)} chars; must be at most "
            f"{MAX_QUESTION_CHARS} including the repo tag and any options "
            "(refused, not truncated)"
        )
    return text


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
    text = format_message(from_agent, question, options)
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
