"""Single-slot question queue over the tickets table (crt#67), and admission
control on that slot (crt#96).

One question is visible on Zach's phone at a time: three in flight looked like
three separate pings, the spam this relay exists to avoid. sweep_and_promote()
is the only place a ticket moves 'queued' -> 'pending'; it is a plain
read-then-maybe-write against sqlite, safe from anywhere holding a connection,
so calling it more often only promotes sooner.
"""
import calendar
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

MAX_QUESTION_CHARS = 140
QUESTION_TTL_SECS = int(os.environ.get("ZAXON_QUESTION_TTL_SECS", "3600"))

ADMIT_WINDOW_SECS = 24 * 3600
ADMIT_MAX_UNANSWERED = int(os.environ.get("ZAXON_ADMIT_MAX_UNANSWERED", "10"))

HERMES_BIN = str(Path.home() / ".hermes" / "hermes-agent" / ".venv" / "bin" / "hermes")

# The Baileys bridge, which hermes-agent runs as a gateway child. The relay
# container shares the gateway's network namespace (network_mode:
# "service:gateway"), so this loopback address is the bridge's, not ours.
# It is the ONLY way to edit a sent message: hermes-agent's WhatsApp adapter
# never overrides edit_message, so BasePlatformAdapter.edit_message returns
# "Not supported" and every caller falls back to sending a SECOND message --
# the exact spam this relay exists to prevent.
BRIDGE_URL = os.environ.get("ZAXON_BRIDGE_URL", "http://127.0.0.1:3000")

# `hermes send --to whatsapp:Zach` resolves the name; the bridge's /edit
# needs the JID itself, and the send payload may not carry it back.
CHAT_ID = os.environ.get("ZAXON_CHAT_ID", "231099456315524@lid")


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
        "UPDATE tickets SET status='pending', wa_message_id=?, chat_id=? WHERE id=?",
        (payload.get("message_id"), payload.get("chat_id") or CHAT_ID, ticket_id),
    )
    conn.commit()
    return "pending"


def send_now(from_agent: str, message: str, sender=None) -> dict:
    text = validate_message(from_agent, message)
    send = sender or _default_sender
    try:
        return send(text)
    except Exception as e:
        return {"success": False, "error": str(e)}


def _default_editor(chat_id: str, message_id: str, text: str) -> dict:
    body = json.dumps({"chatId": chat_id, "messageId": message_id, "message": text})
    req = urllib.request.Request(
        f"{BRIDGE_URL}/edit", data=body.encode(), method="POST"
    )
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode() or "{}")


def edit_delivered(conn, ticket_id: str, text: str, editor=None) -> None:
    """Replaces the text of the message already on Zach's phone. Raises on
    any failure and leaves the row untouched -- the old message is still
    what he can see, so the row must not start claiming otherwise, and
    falling back to a second message is the one thing this must never do.
    `editor` is injectable for tests."""
    row = conn.execute(
        "SELECT wa_message_id, chat_id FROM tickets WHERE id=?", (ticket_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"no such ticket {ticket_id}")
    message_id, chat_id = row
    if not message_id:
        raise ValueError(f"ticket {ticket_id} has no delivered message to edit")
    payload = (editor or _default_editor)(chat_id or CHAT_ID, message_id, text)
    if not payload.get("success"):
        raise RuntimeError(f"bridge refused the edit: {payload.get('error', 'unknown')}")


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


def _window_start(now=None) -> str:
    return time.strftime(
        "%Y-%m-%dT%H:%M:%SZ",
        time.gmtime((now if now is not None else time.time()) - ADMIT_WINDOW_SECS),
    )


def admission_error(conn, from_agent: str, now=None):
    """Why this caller may not take the slot, or None (crt#96). The slot is a
    human and cannot be scaled, yet it was allocated first-come: 90 of 138
    tickets came from two callers with zero replies between them, ever. Keyed
    on the caller's own answer rate over a ROLLING window, so it readmits
    itself and there is nothing for a human to reset."""
    asked, answered = conn.execute(
        "SELECT COUNT(*), COUNT(answered_at) FROM tickets "
        "WHERE from_agent=? AND created_at>=?",
        (from_agent, _window_start(now)),
    ).fetchone()
    if answered or asked < ADMIT_MAX_UNANSWERED:
        return None
    return (
        f"{from_agent} has asked {asked} question(s) in the last 24h and had none "
        "answered, so it is holding the only slot there is away from callers who "
        "do get answers. Refused until one is answered or those age out. Not a "
        "relay fault and not retryable -- a question nobody answers needs a "
        "different channel, not another attempt."
    )


def slot_report(conn, ticket_id: str) -> dict:
    """How many questions clear before this one reaches the phone, and the
    worst case if each expires rather than being answered. `pending` alone read
    the same next-up and 18 hours deep (crt#89)."""
    row = conn.execute(
        "SELECT status, created_at FROM tickets WHERE id=?", (ticket_id,)
    ).fetchone()
    if row is None:
        return {}
    status, created_at = row
    if status != "queued":
        ahead = 0
    else:
        ahead = conn.execute(
            "SELECT COUNT(*) FROM tickets WHERE status='pending' "
            "OR (status='queued' AND created_at<?)",
            (created_at,),
        ).fetchone()[0]
    return {
        "queued_ahead": ahead,
        "est_wait_hours": round(ahead * QUESTION_TTL_SECS / 3600, 1),
    }
