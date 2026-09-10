"""Per-from_agent question queue over the tickets table (crt#67, crt#230), and
admission control on each agent's slot (crt#96).

One question per repo is visible on Zach's phone at a time: three in flight
from the same repo looked like three separate pings, the spam this relay
exists to avoid. The slot is keyed on from_agent, not global (crt#230,
crt#232) -- a chatty caller edits only its own message and cannot starve or
overwrite a quiet one. sweep_and_promote() is the only place a ticket moves
'queued' -> 'pending'; it is a plain read-then-maybe-write against sqlite,
safe from anywhere holding a connection, so calling it more often only
promotes sooner. deliver() edits in place (crt#100), scoped to the ticket's
own from_agent.
"""
import calendar
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

MAX_QUESTION_CHARS = 140
MAX_QUESTION_LINES = 3  # one question per ticket, crt#190
_ENUMERATED_ASK_RE = re.compile(r"(?:^|\n)\s*\d+[.)]\s")
QUESTION_TTL_SECS = int(os.environ.get("ZAXON_QUESTION_TTL_SECS", "3600"))

GATEWAY_CACHE_AUDIO_DIR = Path.home() / ".hermes" / "cache" / "audio"

STT_COMMAND = os.environ.get(
    "HERMES_LOCAL_STT_COMMAND",
    "/opt/zaxon-relay/bin/whisper_stt.sh {input_path} {output_dir} {language}",
)

ADMIT_WINDOW_SECS = 24 * 3600
ADMIT_MAX_UNANSWERED = int(os.environ.get("ZAXON_ADMIT_MAX_UNANSWERED", "10"))

HERMES_BIN = str(Path.home() / ".hermes" / "hermes-agent" / ".venv" / "bin" / "hermes")

# The Baileys bridge, reached over loopback because the relay container
# shares the gateway's network namespace (compose.yaml: network_mode
# "service:gateway"). It is the only way to edit a sent message -- see
# TestEditDelivered for why that matters (hermes's WhatsApp adapter has
# no edit_message of its own).
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


def validate_single_question(question: str) -> None:  # crt#190
    if question.count("?") > 1:
        raise ValueError(
            "question contains more than one '?' -- one question per ticket "
            "(Zach 2026-08-20); open a separate ticket per question instead "
            "of bundling"
        )
    if len(_ENUMERATED_ASK_RE.findall(question)) > 1:
        raise ValueError(
            "question contains more than one enumerated item (e.g. '1. ... "
            "2. ...') -- one question per ticket (Zach 2026-08-20); use the "
            "options= poll for multiple choices on ONE question, or open a "
            "separate ticket per question"
        )
    if question.count("\n") >= MAX_QUESTION_LINES:
        raise ValueError(
            f"question spans more than {MAX_QUESTION_LINES} lines -- keep it "
            "short enough to fit a phone screen (Zach 2026-08-20)"
        )


def validate_message(repo: str, question: str, options=None) -> str:
    """Measures what actually lands on the phone -- repo tag and option
    lines included -- because 140 is inclusive (Zach 2026-08-25). Measuring
    the question alone let the rendered message run ~19 chars over.

    Refuses rather than truncating: a caller who can't fit it hasn't
    decided what it's asking. Returns the rendered text so callers don't
    render twice."""
    validate_repo(repo)
    validate_single_question(question)
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


def _last_delivered(conn, exclude_ticket_id=None, from_agent=None):
    """The message this ticket may reuse by editing. Scoped to from_agent
    for the ask_zach queue (crt#232) -- without it, an unrelated agent's
    ticket edits *the* one message on Zach's phone, not its own."""
    clauses = ["wa_message_id IS NOT NULL"]
    params = []
    if from_agent is not None:
        clauses.append("from_agent=?")
        params.append(from_agent)
    if exclude_ticket_id is not None:
        clauses.append("id != ?")
        params.append(exclude_ticket_id)
    query = (
        "SELECT wa_message_id, chat_id FROM tickets WHERE "
        + " AND ".join(clauses)
        + " ORDER BY created_at DESC LIMIT 1"
    )
    return conn.execute(query, params).fetchone()


def deliver(conn, ticket_id: str, from_agent: str, question: str, options, sender=None, editor=None) -> str:
    """Edits the prior message delivered for this SAME from_agent in place
    (crt#100, crt#232), falling back to sender() only when there's none to
    edit or the edit fails. Stamps delivered_at so the TTL is counted from
    when the question actually reached the phone, not from when it was
    filed (crt#231). Returns 'pending' or 'failed'. Stamps delivered_via
    ('edit' or 'send') so a caller can weigh a 'pending' status accordingly --
    an edit's "success" is only the bridge's own report against a message id
    that is never independently confirmed to still be live (crt#244), while
    a fresh send's message_id came back from that same send call.
    `sender`/`editor` are injectable for tests."""
    send = sender or _default_sender
    edit = editor or _default_editor
    text = format_message(from_agent, question, options)
    now = _iso_now()

    prior = _last_delivered(conn, exclude_ticket_id=ticket_id, from_agent=from_agent)
    if prior and prior[0]:
        prior_message_id, prior_chat_id = prior
        try:
            edit_payload = edit(prior_chat_id or CHAT_ID, prior_message_id, text)
        except Exception:
            edit_payload = {"success": False}
        if edit_payload.get("success"):
            conn.execute(
                "UPDATE tickets SET status='pending', wa_message_id=?, chat_id=?, delivered_at=?, "
                "delivered_via='edit' WHERE id=?",
                (prior_message_id, prior_chat_id or CHAT_ID, now, ticket_id),
            )
            conn.commit()
            return "pending"

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
        "UPDATE tickets SET status='pending', wa_message_id=?, chat_id=?, delivered_at=?, "
        "delivered_via='send' WHERE id=?",
        (payload.get("message_id"), payload.get("chat_id") or CHAT_ID, now, ticket_id),
    )
    conn.commit()
    return "pending"


def send_now(conn, from_agent: str, message: str, sender=None, editor=None) -> dict:
    text = validate_message(from_agent, message)

    pending = conn.execute("SELECT 1 FROM tickets WHERE status='pending' LIMIT 1").fetchone()
    if pending is None:
        prior = _last_delivered(conn)
        if prior and prior[0]:
            message_id, chat_id = prior
            try:
                edit_payload = (editor or _default_editor)(chat_id or CHAT_ID, message_id, text)
            except Exception:
                edit_payload = {"success": False}
            if edit_payload.get("success"):
                return {"success": True, "message_id": message_id, "chat_id": chat_id or CHAT_ID}

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


def _transcribe(audio_path: str, language: str = "en") -> str:
    with tempfile.TemporaryDirectory() as out:
        cmd = STT_COMMAND.format(input_path=audio_path, output_dir=out, language=language)
        subprocess.run(cmd, shell=True, check=True, capture_output=True)
        return (Path(out) / "transcript.txt").read_text().strip()


def _recover_from_gateway_cache(conn, ticket_id: str, created_at: str, cache_dir=None, transcribe=None) -> bool:
    cache_dir = cache_dir or GATEWAY_CACHE_AUDIO_DIR
    transcribe = transcribe or _transcribe
    if not cache_dir.is_dir():
        return False
    threshold = _epoch(created_at)
    candidates = sorted(
        (p for p in cache_dir.iterdir() if p.is_file() and p.stat().st_mtime > threshold),
        key=lambda p: p.stat().st_mtime,
    )
    if not candidates:
        return False
    try:
        text = transcribe(str(candidates[0]))
    except (subprocess.CalledProcessError, OSError):
        return False
    if not text:
        return False
    conn.execute(
        "UPDATE tickets SET status='answered', answer=?, answered_at=?, via='voice' WHERE id=?",
        (text, _iso_now(), ticket_id),
    )
    conn.commit()
    return True


def sweep_and_promote(conn, sender=None, editor=None, cache_dir=None, transcribe=None) -> None:
    """Expires any overdue 'pending' ticket, then promotes the oldest
    'queued' ticket for each from_agent that doesn't already hold a
    still-fresh 'pending' one. The slot is per from_agent (crt#230): a
    chatty repo's own backlog no longer blocks a different repo's question
    from reaching the phone. Staleness is measured from delivered_at, the
    moment the question actually reached the phone, falling back to
    created_at for rows delivered before that column existed (crt#231)."""
    pending_rows = conn.execute(
        "SELECT id, from_agent, created_at, delivered_at FROM tickets WHERE status='pending'"
    ).fetchall()
    fresh_agents = set()
    for ticket_id, from_agent, created_at, delivered_at in pending_rows:
        clock = delivered_at or created_at
        if time.time() - _epoch(clock) <= QUESTION_TTL_SECS:
            fresh_agents.add(from_agent)
            continue
        if not _recover_from_gateway_cache(conn, ticket_id, clock, cache_dir, transcribe):
            conn.execute("UPDATE tickets SET status='stale' WHERE id=?", (ticket_id,))
            conn.commit()

    queued = conn.execute(
        "SELECT id, from_agent, question, options FROM tickets "
        "WHERE status='queued' ORDER BY created_at"
    ).fetchall()
    promoted_agents = set()
    for ticket_id, from_agent, question, options_json in queued:
        if from_agent in fresh_agents or from_agent in promoted_agents:
            continue
        options = json.loads(options_json) if options_json else None
        deliver(conn, ticket_id, from_agent, question, options, sender=sender, editor=editor)
        promoted_agents.add(from_agent)


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
    """How many of THIS from_agent's own questions clear before this one
    reaches the phone, and the worst case if each expires rather than being
    answered. Scoped to from_agent (crt#230): with a per-agent slot, a
    ticket only waits behind its own repo's earlier tickets, not every
    repo's. `pending` alone read the same next-up and 18 hours deep
    (crt#89); an already-overdue pending ticket is excluded (crt#231) --
    the next sweep frees it, so it does not cost this ticket a full TTL."""
    row = conn.execute(
        "SELECT status, created_at, from_agent FROM tickets WHERE id=?", (ticket_id,)
    ).fetchone()
    if row is None:
        return {}
    status, created_at, from_agent = row
    if status != "queued":
        ahead = 0
    else:
        rows = conn.execute(
            "SELECT status, created_at, delivered_at FROM tickets WHERE from_agent=? AND "
            "(status='pending' OR (status='queued' AND created_at<?))",
            (from_agent, created_at),
        ).fetchall()
        now = time.time()
        ahead = sum(
            1 for st, ca, da in rows
            if st == "queued" or now - _epoch(da or ca) <= QUESTION_TTL_SECS
        )
    return {
        "queued_ahead": ahead,
        "est_wait_hours": round(ahead * QUESTION_TTL_SECS / 3600, 1),
    }
