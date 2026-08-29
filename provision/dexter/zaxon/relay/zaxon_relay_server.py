#!/usr/bin/env python3
"""Zaxon relay MCP server -- Phase 1 landing, plus a question queue (crt#67).

Any MCP-aware agent calls ask_zach() to relay a question to Zach over WhatsApp
and polls check_zach_reply() for the answer. Delivery shells out to `hermes
send` (LLM-free, agent-loop-free) rather than touching hermes-agent's gateway
process, and zaxon_relay_watcher.py tails agent.log for the reply; ticket state
is our own sqlite file. The single slot, its TTL, the 140-char rendered-message
guard and the admission check all live in zaxon_relay_queue.py.
"""
import json
import time
import uuid

from mcp.server.mcpserver import MCPServer

from zaxon_relay_db import get_conn
from zaxon_relay_inbox import fetch_inbox as _fetch_inbox
from zaxon_relay_queue import (
    MAX_QUESTION_CHARS,
    admission_error,
    edit_delivered,
    send_now,
    slot_report,
    sweep_and_promote,
    validate_message,
)

mcp = MCPServer(
    "zaxon",
    instructions=(
        "Hook-agnostic relay into Zach's WhatsApp. Use ask_zach to send him a "
        "question and get back a ticket_id; poll check_zach_reply with that "
        "ticket_id until status is 'answered'. Do not block waiting -- this "
        "is a human reply, it can take minutes. Only one question reaches "
        "Zach's phone at a time -- extra ones queue and are sent in order "
        "as earlier ones are answered or go stale; queued_ahead and "
        "est_wait_hours come back with every reply. A caller whose questions "
        "are never answered is refused, not queued. from_agent is your REPO "
        "name -- it renders bold as the first thing Zach reads. The whole "
        f"rendered message must be at most {MAX_QUESTION_CHARS} characters, "
        "repo tag and option lines included; prefer a multiple-choice poll "
        "(pass options) over free text. To change a question already sent, "
        "call revise_zach_question -- never ask a second time. fetch_inbox "
        "reads messages that arrived matching no ticket of yours -- an "
        "unsolicited note from Zach, or a late reply to something that "
        "already went stale."
    ),
)


@mcp.tool()
def ask_zach(question: str, from_agent: str = "agent", options: list[str] | None = None) -> dict:
    """Relay a question to Zach over WhatsApp. Returns immediately with a
    ticket_id -- this does not wait for his reply. Call check_zach_reply
    with the returned ticket_id to poll for the answer. Only one question
    is ever in flight to his phone; if another is already pending, this one
    queues and is sent once the slot frees (answered or stale). queued_ahead
    and est_wait_hours come back with the ticket -- how many questions clear
    first, worst case if each expires -- so you can decide whether to wait.

    Refuses (status 'refused') rather than truncating if the rendered message
    exceeds MAX_QUESTION_CHARS -- the limit counts the bold repo tag and every
    option line, not the question alone. Also refuses, NOT retryably, a caller
    that has asked repeatedly in the last 24h with nothing answered: the slot
    is a human's attention and it is being spent on everyone else's behalf.

    from_agent is your REPO name. options, if given, renders as a numbered poll."""
    try:
        validate_message(from_agent, question, options)
    except ValueError as e:
        return {"status": "refused", "error": str(e)}
    ticket_id = uuid.uuid4().hex[:8]
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    conn = get_conn()
    try:
        denied = admission_error(conn, from_agent)
        if denied:
            return {"status": "refused", "error": denied}

        conn.execute(
            "INSERT INTO tickets (id, from_agent, question, status, created_at, options) "
            "VALUES (?, ?, ?, 'queued', ?, ?)",
            (ticket_id, from_agent, question, now, json.dumps(options) if options else None),
        )
        conn.commit()

        sweep_and_promote(conn)

        status = conn.execute(
            "SELECT status, answer FROM tickets WHERE id=?", (ticket_id,)
        ).fetchone()
        status, answer = status
        result = {"ticket_id": ticket_id, "status": status, **slot_report(conn, ticket_id)}
        if status == "failed":
            result["error"] = answer
        return result
    finally:
        conn.close()


@mcp.tool()
def revise_zach_question(
    ticket_id: str, question: str, options: list[str] | None = None
) -> dict:
    """Change a question you have already asked, IN PLACE. If it has reached
    Zach's phone the message there is edited; he is not pinged twice. This
    is the only sanctioned way to change your mind -- asking again spends a
    second notification on the same question, which is what the single-slot
    queue exists to prevent.

    Only 'queued' (not yet sent, so the row is simply updated) and 'pending'
    (sent, so the message is edited) can be revised. An answered question is
    not revisable: ask a new one. Refuses (status 'refused') if too long or the repo tag is bad."""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT status, from_agent FROM tickets WHERE id=?", (ticket_id,)
        ).fetchone()
        if row is None:
            return {"status": "not_found"}
        status, from_agent = row
        if status not in ("queued", "pending"):
            return {
                "status": status,
                "error": f"a {status} question cannot be revised -- ask a new one",
            }

        try:
            text = validate_message(from_agent, question, options)
        except ValueError as e:
            return {"status": "refused", "error": str(e)}
        if status == "pending":
            # Raises rather than falling back to a second message: if the
            # edit fails, what Zach can see is still the old question.
            edit_delivered(conn, ticket_id, text)

        conn.execute(
            "UPDATE tickets SET question=?, options=? WHERE id=?",
            (question, json.dumps(options) if options else None, ticket_id),
        )
        conn.commit()
        return {"ticket_id": ticket_id, "status": status, "revised": True}
    finally:
        conn.close()


@mcp.tool()
def check_zach_reply(ticket_id: str) -> dict:
    """Poll for Zach's WhatsApp reply to a question sent via ask_zach.
    status is one of: queued, pending, answered, failed, stale, not_found.
    'queued' means another question is still waiting on Zach's phone, and
    queued_ahead / est_wait_hours say how far back; 'stale' means this one
    expired unanswered and its slot was freed -- if you still need an answer,
    ask again."""
    conn = get_conn()
    try:
        sweep_and_promote(conn)
        row = conn.execute(
            "SELECT status, answer FROM tickets WHERE id=?", (ticket_id,)
        ).fetchone()
        report = slot_report(conn, ticket_id)
    finally:
        conn.close()

    if row is None:
        return {"status": "not_found"}
    status, answer = row
    result = {"status": status, **report}
    if status == "answered":
        result["answer"] = answer
    elif status == "failed":
        result["error"] = answer
    return result


@mcp.tool()
def fetch_inbox(limit: int = 50) -> dict:
    """Read inbound messages matching no pending ticket, verbatim, newest first."""
    return {"entries": _fetch_inbox(limit=limit)}


@mcp.tool()
def send_zach(message: str, from_agent: str = "agent") -> dict:
    """One-way note to Zach, no reply expected -- use ask_zach if you need one."""
    try:
        payload = send_now(from_agent, message)
    except ValueError as e:
        return {"status": "refused", "error": str(e)}
    if not payload.get("success"):
        return {"status": "failed", "error": payload.get("error", "unknown send failure")}
    return {"status": "sent", "message_id": payload.get("message_id")}


if __name__ == "__main__":
    # Bound to all interfaces (not just loopback) so it's reachable over
    # Tailscale from other machines (e.g. mandark), not just from other WSL
    # distros on dexter. No auth on this server yet -- this also means it's
    # reachable from the LAN, not just the tailnet. Revisit once per-consumer
    # auth lands (see ZAXON_ROADMAP.md Phase 1).
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8643, streamable_http_path="/mcp")
