#!/usr/bin/env python3
"""Read the zaxon relay's real state and print it as status.json.

Runs ON dexter; the ledger is a local sqlite file. Reads only. The verdict
ladder is pinned by tests/test_zaxon_status_collect.py, and stale_slot_hours
by its SlotCost cases -- a single slot (crt#67) means an ignored question
holds the channel for its full TTL, so a miss is a cost to every other caller.
"""
import json
import os
import sqlite3
import sys
import time

DB = os.environ.get("ZAXON_DB", "/srv/zaxon/data/zaxon_relay/tickets.db")
TTL_H = int(os.environ.get("ZAXON_QUESTION_TTL_SECS", "3600")) / 3600
WINDOW_H = 24


def _epoch(ts):
    return time.mktime(time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")) - time.timezone


def collect():
    try:
        conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        rows = conn.execute(
            "SELECT id, from_agent, status, created_at, answered_at, question FROM tickets"
        ).fetchall()
    except sqlite3.Error as e:
        return {"readable": False, "path": DB, "error": str(e)}

    now = time.time()
    cut = now - WINDOW_H * 3600
    tickets = [
        {"id": i, "from": f, "status": s, "created_at": c, "answered_at": a,
         "question": q, "_t": _epoch(c)}
        for (i, f, s, c, a, q) in rows
    ]
    win = [t for t in tickets if t["_t"] >= cut]

    def tally(ts):
        out = {}
        for t in ts:
            out[t["status"]] = out.get(t["status"], 0) + 1
        return out

    senders = {}
    for t in win:
        s = senders.setdefault(t["from"], {"from": t["from"], "sent": 0,
                                           "answered": 0, "stale": 0, "failed": 0})
        s["sent"] += 1
        if t["status"] in s:
            s[t["status"]] += 1

    open_now = [t for t in tickets if t["status"] in ("pending", "queued")]
    pending = next((t for t in open_now if t["status"] == "pending"), None)
    answered = [t for t in tickets if t["answered_at"]]
    answered.sort(key=lambda t: t["answered_at"])
    recent = sorted(tickets, key=lambda t: t["_t"], reverse=True)[:12]

    return {
        "readable": True,
        "path": DB,
        "ttl_hours": TTL_H,
        "window_hours": WINDOW_H,
        "totals": tally(tickets),
        "window": tally(win),
        "window_sent": len(win),
        "stale_slot_hours": round(tally(win).get("stale", 0) * TTL_H, 1),
        "queued": sum(1 for t in open_now if t["status"] == "queued"),
        "slot": None if pending is None else {
            "id": pending["id"], "from": pending["from"],
            "age_hours": round((now - pending["_t"]) / 3600, 1),
            "question": pending["question"][:140],
        },
        "last_answered_at": answered[-1]["answered_at"] if answered else None,
        "senders": sorted(senders.values(), key=lambda s: -s["sent"]),
        "recent": [{k: t[k] for k in
                    ("id", "from", "status", "created_at", "answered_at")}
                   | {"question": t["question"][:140]} for t in recent],
    }


def verdict(ledger, relay):
    """Ordered so the loudest true thing wins. A relay that answers is never
    OK on its own -- 'the port is open' is not 'the human is reachable'."""
    if not relay.get("answers"):
        return "DOWN", "the relay does not answer -- no question can reach Zach"
    if not ledger.get("readable"):
        return "BLIND", f"the relay answers but its ticket store is unreadable ({ledger.get('error')})"
    w, sent = ledger["window"], ledger["window_sent"]
    if w.get("failed"):
        return "DOWN", (f"{w['failed']} send(s) failed in {ledger['window_hours']}h -- "
                        "the relay accepts questions and WhatsApp does not take them")
    slot = ledger["slot"]
    if slot and slot["age_hours"] > ledger["ttl_hours"]:
        return "WEDGED", (f"the one slot has held {slot['id']} for {slot['age_hours']}h, "
                          "past its own TTL, and the sweep has not freed it")
    if sent and not w.get("answered"):
        return "UNANSWERED", (
            f"{sent} question(s) sent in {ledger['window_hours']}h, none answered; "
            f"{ledger['stale_slot_hours']}h of the single slot went to tickets that expired")
    if not sent:
        return "QUIET", (f"no question in {ledger['window_hours']}h -- the relay answers, "
                         "but nothing has exercised the path to the phone")
    return "OK", f"{w.get('answered', 0)} of {sent} question(s) answered in {ledger['window_hours']}h"


if __name__ == "__main__":
    relay = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {"answers": False}
    containers = json.loads(sys.argv[2]) if len(sys.argv) > 2 else []
    hazards = json.loads(sys.argv[3]) if len(sys.argv) > 3 else []
    ledger = collect()
    v, why = verdict(ledger, relay)
    cadence = int(os.environ.get("CADENCE_MIN", "60"))
    grace = int(os.environ.get("GRACE_MIN", "30"))
    now = time.time()
    stamp = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
    print(json.dumps({
        "schema": 1,
        "service": "zaxon",
        "host": "dexter",
        "generated": stamp(now),
        "valid_until": stamp(now + (cadence + grace) * 60),
        "cadence_minutes": cadence,
        "verdict": v,
        "why": why,
        "relay": relay,
        "containers": containers,
        "hazards": hazards,
        "ledger": ledger,
    }, indent=2))
