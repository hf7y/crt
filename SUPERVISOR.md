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

## Playbooks built this session
- **`status`** (was already there as the informal "local trigger" logic,
  now a named playbook) — "what's up"/"any reports"/etc. Reads
  `~/reports/crt/LATEST.md` + `.claude/QUESTIONS.md` directly, speaks a
  count + offers to print. Zero Claude call.
- **`run_tests`** — "run the tests"/"run the test suite"/"are the tests
  passing" runs `tests/run_tests.sh` right there on the console and speaks
  a pass/fail summary. This is the supervisor directly using this
  session's own new test suite — a routine maintenance question that
  should never need to wake Claude to answer.
- **`what_time`** — "what time is it"/"what's the time" — the simplest
  possible playbook, included mostly to prove the pattern scales down to
  the trivial case cleanly, not because it's an important feature.

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

## Open items
- No usage tracking yet on which requests fall through to Claude most
  often — that's the actual signal for "what to playbook next," and
  doesn't exist. A cheap first version: append the raw text to a log file
  whenever `handle()` falls through, and eyeball it periodically.
- ~~No playbook yet for the display-calibration game~~ **DONE
  (2026-07-20)**: `calibrate` runs `crt-calibrate-display.py show` (the
  single-shot pattern render only, not the interactive multi-round `run`
  loop — that needs real voice back-and-forth, which doesn't fit a
  one-shot request/response playbook).
- The playbook registry currently lives inline in `crt-secretary.py` — if
  the list grows much past what's here, worth splitting into its own
  `bin/crt-playbooks/` directory, one file per playbook, rather than one
  growing script. Not done preemptively (three playbooks doesn't justify
  it yet) — noted so it isn't rediscovered as a surprise refactor later.

## Status
`bin/crt-secretary.py` refactored to the playbook model this session,
3 playbooks built, all covered by `tests/test_secretary.py` against
synthetic report/question files and a real (this repo's own)
`tests/run_tests.sh` invocation. Untested against a live Claude Code pane
or real voice traffic — same caveat as the rest of `crt-secretary.py`,
see `SECRETARY.md`.
