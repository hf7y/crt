---
description: Nightly thorough pass on the crt voice console -- code-shaped backlog only, scoped by FOCUS.md
---

<!-- Adapted from scheduler/examples/nightly-batch.md.template and the
     home-assistant project's own no-tracker variant. No web tracker/
     INTAKE.md for this project -- FOCUS.md's own "Now" and "Deferred"
     sections are the source of truth instead. -->

Read `.claude/FOCUS.md` first. Everything below is scoped BY that file --
if something looks like an easy win but isn't in service of the current
focus, write it up in the report as deferred; do not implement it just
because it's sitting there.

This project is a physical voice console. As of 2026-07-23, `potato` (a
Raspberry Pi, real hardware, `ssh potato` -- key auth, alias in this
account's persistent `~/.ssh/config`, NOT the disposable clone, so it
survives every cycle's `git reset --hard`) is the actual live console,
same role `dexter`/`crt-vm` used to play (that combo is now legacy --
see `.claude/SESSION-STATE.md`'s 2026-07-23 section for the full
topology). **`ssh potato` access means real STT-pipeline/audio work on
potato IS in scope for an unattended run** -- it is NOT "needs hands on
hardware" just because it involves a remote physical box, the same way
`ssh crt-vm` access made VM-side work in scope before it. Concretely in
scope via SSH: running/reading `~/.crt/*.log` on potato, restarting a
tmux window there with a fixed env var, deploying an updated script
(`scp` + diff-verify, per `.claude/SESSION-STATE.md`'s "always diff
after scp'ing" note), running `bin/crt-earcon-loopback-test.py` there
and reading its output. Still genuinely out of scope / branch around:
anything that needs a HUMAN physically present (confirming a sound was
actually heard, plugging in a cable, a 3D print, wiring a hookswitch) --
the loopback test's own measurement is evidence, not proof; note where
its result still needs Zach's own ear to fully confirm, don't claim it
as verified-done on the tool's numbers alone. If `ssh potato` itself
fails (host key, auth, connection) treat it exactly like the existing
crt-vm-access failure policy below: don't spend the whole cycle
debugging it, note it in the report, continue with whatever else is in
scope.

## 1. Orient

`git log --oneline -10`, current branch state, `README.md`, `HANDOFF.md`
(persistent state/access notes -- trust it over assumptions), `AUDIO-DEBUG.md`,
and `.claude/FOCUS.md`. If the previous nightly run left work in progress
(check `~/reports/crt/` for the last report), pick up from there rather
than starting over.

## 2. Re-verify anything a previous run claimed was working

Do not trust a prior run's own claims. For any script/tool a previous
cycle said it "finished," re-read it and check it against FOCUS.md's
actual acceptance bar -- most items here are explicitly marked
`[needs VM test]`/needs a live human ear precisely because they can't be
fully verified from here; don't upgrade that marker to "done" without
either an actual live confirmation from the human, OR (2026-07-23) a
concrete measurement from a tool built for exactly that (e.g.
`bin/crt-earcon-loopback-test.py`'s acoustic detection) -- a strong
measurement is real evidence and worth acting on, but still note in the
report where it stops short of Zach's own ear as final confirmation.

## 3. Push forward on whatever IS in scope per FOCUS.md

Real progress, not just re-reading the same status. Commit as you
complete meaningful chunks -- don't save it all for one giant commit at
the end. If a task needs the user's own hands (plugging something in, a
live VM session, a physical test), do not attempt to route around it --
write the specific blocker and exactly what's needed from them in the
report.

## 4. Stress-test what you touched

Read through the change once more for the failure modes this project
actually has (stale/flatlined audio capture, a second reader starving the
first, a control-file race) rather than declaring victory on the code
compiling/parsing.

## 5. Write the report

`~/reports/crt/$(date +%Y-%m-%d).md`, and update `~/reports/crt/LATEST.md`
to match it. Cover exactly: what got built/fixed tonight (with commit
references), what was deliberately deferred because it's physical/needs a
live VM (and what exactly the human needs to do), any new issues
discovered, and any open questions that need a human decision (append to
`.claude/QUESTIONS.md`, create it if absent, using the standard `> `
inline-reply convention every other project uses).

## 6. Before finishing

Confirm every meaningful change has a real commit, pushed to `origin`
(the local bare repo at `/home/zach/git-remotes/crt.git` -- this is not
GitHub, just a disposable-clone target, so pushing here is safe and
expected every run). An overnight run that isn't saved anywhere didn't
happen.
