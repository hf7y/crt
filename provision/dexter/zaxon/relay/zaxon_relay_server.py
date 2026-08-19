#!/usr/bin/env python3
"""Zaxon relay MCP server -- Phase 1 landing.

Exposes the hook-agnostic contract from the roadmap: any MCP-aware agent can
call ask_zach() to relay a question to Zach over WhatsApp, then poll
check_zach_reply() for his answer. Deliberately does not touch hermes-agent's
own gateway process -- it shells out to `hermes send` (documented as
LLM-free, agent-loop-free) for delivery, and relies on zaxon_relay_watcher.py
tailing agent.log to capture the reply. Ticket state lives in a small sqlite
file, not in hermes-agent's own storage.
"""
import json
import subprocess
import time
import uuid
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from zaxon_relay_db import get_conn

HERMES_BIN = str(Path.home() / ".hermes" / "hermes-agent" / ".venv" / "bin" / "hermes")

mcp = MCPServer(
    "zaxon",
    instructions=(
        "Hook-agnostic relay into Zach's WhatsApp. Use ask_zach to send him a "
        "question and get back a ticket_id; poll check_zach_reply with that "
        "ticket_id until status is 'answered'. Do not block waiting -- this "
        "is a human reply, it can take minutes."
    ),
)


@mcp.tool()
def ask_zach(question: str, from_agent: str = "agent") -> dict:
    """Relay a question to Zach over WhatsApp. Returns immediately with a
    ticket_id -- this does not wait for his reply. Call check_zach_reply
    with the returned ticket_id to poll for the answer."""
    ticket_id = uuid.uuid4().hex[:8]
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO tickets (id, from_agent, question, status, created_at) "
            "VALUES (?, ?, ?, 'pending', ?)",
            (ticket_id, from_agent, question, now),
        )
        conn.commit()

        text = (
            f"\U0001F500 [{from_agent}] asks (reply to this message to answer, "
            f"#{ticket_id}):\n\n{question}"
        )
        try:
            proc = subprocess.run(
                [HERMES_BIN, "send", "--to", "whatsapp:Zach", text, "--json"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            payload = json.loads(proc.stdout or "{}")
        except Exception as e:  # noqa: BLE001 -- surfaced to the caller, not swallowed
            conn.execute(
                "UPDATE tickets SET status='failed', answer=? WHERE id=?",
                (str(e), ticket_id),
            )
            conn.commit()
            return {"ticket_id": ticket_id, "status": "failed", "error": str(e)}

        if not payload.get("success"):
            err = payload.get("error", "unknown send failure")
            conn.execute(
                "UPDATE tickets SET status='failed', answer=? WHERE id=?",
                (err, ticket_id),
            )
            conn.commit()
            return {"ticket_id": ticket_id, "status": "failed", "error": err}

        conn.execute(
            "UPDATE tickets SET wa_message_id=? WHERE id=?",
            (payload.get("message_id"), ticket_id),
        )
        conn.commit()
        return {"ticket_id": ticket_id, "status": "pending"}
    finally:
        conn.close()


@mcp.tool()
def check_zach_reply(ticket_id: str) -> dict:
    """Poll for Zach's WhatsApp reply to a question sent via ask_zach.
    status is one of: pending, answered, failed, not_found."""
    conn = get_conn()
    try:
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
