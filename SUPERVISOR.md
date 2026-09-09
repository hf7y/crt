# The supervisor: 90% offline, Claude Code as the escalation path

The framing Chris gave this session: **crt should be a supervisor first**,
not a terminal that happens to have a voice front end. Most of what gets
said to it in a day is routine and answerable in milliseconds from local
state or a small deterministic script — "what's up," "run the tests,"
"what time is it." Only genuinely novel requests, or something breaking in
a way nothing local knows how to handle, should ever cost a real Claude
Code call. This document names that architecture; `bin/crt-secretary.py`
is the first real implementation of it.

## Why this matters beyond cost
This isn't (only) about API spend. Per `PHILOSOPHY.md` #1 (answer first,
be right later) and #7 (local-first, cloud as a favor asked): a Claude
Code call has real, variable latency (the exact thing
`crt-secretary.py`'s untested idle-detection heuristic has to cope with).
A supervisor that answers "what's up" in under a second, every time,
*feels* like a different, more alive kind of device than one that always
pauses to think — even though Claude is available and would give the same
answer eventually. Fast-and-local for the routine 90% is what makes the
occasional real Claude Code call feel like a deliberate, meaningful
escalation rather than just "the normal amount of waiting."

## The playbook model
`crt-secretary.py` now runs a **playbook registry**: an ordered list of
`(name, match(text) -> bool, handle(text) -> None)`. The first playbook
whose `match()` fires handles the request end-to-end, entirely locally,
and Claude Code is never invoked. If nothing matches, that's the
definition of "novel" — the request falls through to the existing
Claude-routing path (`tmux send-keys` + capture-pane).

This is deliberately **not** an ML intent classifier. Every playbook here
is a plain, auditable string match. Getting fancy about intent detection
locally would fight the entire premise (a small, dumb, fast, honest local
layer, with a very smart but slow/expensive one available on demand) —
the moment local matching gets ambiguous, that ambiguity itself is a
"novel" case, and the right answer is to fall through to Claude, not to
tune a heuristic to guess harder.

## What decides whether something becomes a playbook vs. stays a Claude call
A playbook is worth writing when the answer is **deterministic given
local state** — a file to read, a script to run, a clock to check. The
moment answering requires judgment, synthesis, or anything Claude would
need to *reason* about (not just fetch), it should stay a Claude call.
Concretely: `SECRETARY.md`'s core secretary loop and genuinely open-ended
requests are explicitly **not** playbook candidates — trying to hardcode
those would just be reimplementing Claude Code badly.

## Escalation is not a dead end
When a request falls through to Claude, the goal per Chris's framing is
still to **shrink future playbook gaps**, not just handle this one
instance and forget it. Concretely, once a request escalates and Claude
handles it, a repeat of the *same kind* of request later is a signal that
a new playbook is worth writing (log it — `bin/crt-report.sh`-shaped note,
"this got asked twice, worth a playbook" — not built yet, see open items
below). This keeps the 90%-offline number actually climbing over time
instead of being a one-time snapshot.

## Shipped, and what's still open
`bin/crt-secretary.py`'s `PLAYBOOKS` tuple is the live registry — the
source of truth for which playbooks exist now, not this doc. Every
request that falls through gets appended to `~/.crt/fallthrough.log`
(timestamped, best-effort); nothing reads/summarizes that log yet, so
"this got asked twice, worth a playbook" is still a manual eyeball-it
step, not automated. The registry still lives inline in one script —
worth splitting into its own `bin/crt-playbooks/` directory if it keeps
growing, not done preemptively. Covered by `tests/test_secretary.py`;
untested against a live Claude Code pane or real voice traffic, same
caveat as the rest of `crt-secretary.py` (`SECRETARY.md`).
