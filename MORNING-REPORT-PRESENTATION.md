# Presenting the scheduler's morning report on crt

How the scheduler's cross-project morning report (`Project Archive/
scheduler/bin/morning-report.sh`) maps onto crt's actual output channels
(`SECRETARY.md`: printer / CRT / earpiece), and what that presentation
layer needs from the scheduler side to work well. Built this session as
`bin/crt-present-morning-report.py` + a `morning_report` playbook in
`crt-secretary.py` (`SUPERVISOR.md`) — **zero Claude calls anywhere in
this path**, pure parsing of `morning-report.sh`'s existing stdout.

## The mapping
- **CRT screen: one line per project.** `"<project>: <headline>"`,
  truncated to `CRT_PAGER_WIDTH` (40 by default). Headline = the first
  non-empty content line of that project's section, markdown `#`
  stripped if present. This is deliberately dumb (no NLP, no Claude) —
  see "what would help" below for why that's sometimes a rough headline.
- **Printer: the full report, or one project's full section.** Anything
  longer than a glance belongs on paper, same rule `SECRETARY.md` already
  uses for everything else. `crt-present-morning-report.py print-all` /
  `print <name>`.
- **Earpiece (spoken)**: NOT the report content itself — a spoken count
  ("N projects in this morning's report, printing the full thing") plus
  an offer, then the printer takes the actual payload. Speaking a whole
  multi-project report aloud would be exactly the wall-of-text problem
  `SECRETARY.md` was written to avoid.

## What formatting hooks already exist in the scheduler (used as-is)
- **The section-header shape**: a line of `═`s, `  <name>`, another line
  of `═`s, used identically for every per-project block AND the two
  special blocks (`DEPLOY PENDING`, `Open questions`). This is the one
  thing the presenter actually parses — reliable, already consistent
  across every project's report.
- **`QUESTIONS.md`'s `- **date (context):**` bullet convention** — not
  parsed by this presenter directly (it only sees `morning-report.sh`'s
  already-formatted "Open questions" section), but worth naming since
  it's the upstream structure that section depends on.

## What's missing / would help (a real ask, not a complaint)
- **No machine-parseable one-line summary per project.** Today's
  headline heuristic (first non-empty line of the section, `#` stripped)
  works fine for projects whose report opens with a title line (chezz's
  `# Chezz nightly — 2026-07-18`) but is a poor headline for anything
  that opens with prose (`## TL;DR` sections, `**The Pi was
  unreachable...**`, etc. — see home-assistant's actual reports). A
  standardized required field near the top of every `LATEST.md` — e.g. a
  literal `**Headline:** ...` line every project's report template
  emits — would make the CRT one-liner reliably good instead of
  heuristic-dependent. This is the single highest-value change on the
  scheduler side for this to work well.
- **`morning-report.sh` itself was observed to hang** this session (ran
  it standalone, independent of anything in this repo, timed out at
  120s). Root cause not investigated (likely a slow/unreachable
  per-project `DEPLOY_FRESH_CMD` network probe — home-assistant's own
  report already documents an unreachable-Pi scenario that could match).
  `crt-present-morning-report.py` defends against this with its own
  20s timeout (returns empty rather than hanging the console), but the
  underlying hang is a real bug in shared scheduler infra worth fixing
  there directly — not attempted here, out of scope for this repo, but
  flagging since a console that "just goes quiet" on the actual hardware
  would be a real bad experience.
- **No section identity beyond a display name.** `DEPLOY PENDING` and
  `Open questions` are structurally identical to a per-project section
  (same header shape) but are cross-cutting, not project reports — fine
  for now (the presenter treats every section uniformly), but if the
  scheduler ever adds a third cross-cutting block, worth confirming it
  keeps the same header shape rather than inventing a new one.

## Deployment gap (see VM-JOBS.md)
This all runs correctly on mandark today (where `morning-report.sh` and
the `~/reports/*/`, `~/reports/*/vm/` trees already exist). For the VM to
ever run this playbook itself, it needs the scheduler's aggregate data
(or at least crt's own slice of it) synced TO the VM — the reverse
direction of `bin/crt-sync-vm-reports.sh`, not built. Until then, the
`morning_report` playbook only works from an interactive session running
on mandark, not from crt-vm.

## Status
Built and tested against synthetic data (`tests/
test_present_morning_report.py`, `tests/test_secretary.py`). Confirmed
independently that the real `morning-report.sh` currently hangs (a
scheduler-side bug, not this file's). Never run this presenter against a
real, successful `morning-report.sh` output end-to-end this session.
