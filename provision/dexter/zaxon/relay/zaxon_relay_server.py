#!/usr/bin/env python3
"""Zaxon relay MCP server -- Phase 1 landing, plus a question queue (crt#67).

Exposes the hook-agnostic contract from the roadmap: any MCP-aware agent can
call ask_zach() to relay a question to Zach over WhatsApp, then poll
check_zach_reply() for his answer. Deliberately does not touch hermes-agent's
own gateway process -- it shells out to `hermes send` (documented as
LLM-free, agent-loop-free) for delivery, and relies on zaxon_relay_watcher.py
tailing agent.log to capture the reply. Ticket state lives in a small sqlite
file, not in hermes-agent's own storage.

ask_zach never sends more than one question at a time -- see
zaxon_relay_queue.py for the single-slot queue, staleness TTL, and the
<140-char/multiple-choice style guard that lives there.
"""
import json
import time
import uuid

from mcp.server.mcpserver import MCPServer

from zaxon_relay_db import get_conn
from zaxon_relay_queue import MAX_QUESTION_CHARS, sweep_and_promote, validate_question

mcp = MCPServer(
    "zaxon",
    instructions=(
        "Hook-agnostic relay into Zach's WhatsApp. Use ask_zach to send him a "
        "question and get back a ticket_id; poll check_zach_reply with that "
        "ticket_id until status is 'answered'. Do not block waiting -- this "
        "is a human reply, it can take minutes. Only one question reaches "
        "Zach's phone at a time -- extra ones queue and are sent in order "
        "as earlier ones are answered or go stale. Keep the question under "
        f"{MAX_QUESTION_CHARS} characters and prefer a multiple-choice poll "
        "(pass options) over free text."
    ),
)


@mcp.tool()
def ask_zach(question: str, from_agent: str = "agent", options: list[str] | None = None) -> dict:
    """Relay a question to Zach over WhatsApp. Returns immediately with a
    ticket_id -- this does not wait for his reply. Call check_zach_reply
    with the returned ticket_id to poll for the answer. Only one question
    is ever in flight to his phone; if another is already pending, this one
    queues and is sent once the slot frees (answered or stale). Raises if
    question is MAX_QUESTION_CHARS or longer -- shorten it, don't rely on
    truncation. options, if given, renders as a numbered poll."""
    validate_question(question)
    ticket_id = uuid.uuid4().hex[:8]
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    conn = get_conn()
    try:
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
        result = {"ticket_id": ticket_id, "status": status}
        if status == "failed":
            result["error"] = answer
        return result
    finally:
        conn.close()


@mcp.tool()
def check_zach_reply(ticket_id: str) -> dict:
    """Poll for Zach's WhatsApp reply to a question sent via ask_zach.
    status is one of: queued, pending, answered, failed, stale, not_found.
    'queued' means another question is still waiting on Zach's phone;
    'stale' means this one expired unanswered and its slot was freed --
    if you still need an answer, ask again."""
    conn = get_conn()
    try:
        sweep_and_promote(conn)
        row = conn.execute(
            "SELECT status, answer FROM tickets WHERE id=?", (ticket_id,)
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return {"status": "not_found"}
    status, answer = row
    result = {"status": status}
    if status == "answered":
        result["answer"] = answer
    elif status == "failed":
        result["error"] = answer
    return result


if __name__ == "__main__":
    # Bound to all interfaces (not just loopback) so it's reachable over
    # Tailscale from other machines (e.g. mandark), not just from other WSL
    # distros on dexter. No auth on this server yet -- this also means it's
    # reachable from the LAN, not just the tailnet. Revisit once per-consumer
    # auth lands (see ZAXON_ROADMAP.md Phase 1).
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8643, streamable_http_path="/mcp")
