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

This project is a physical voice console (landline handset + CRT + a
Debian VM on a separate machine, `dexter`) -- most of its backlog is
PHYSICAL (wiring a hookswitch, plugging in a MIDI controller, a 3D print,
a live VM audio test) and cannot be done by an unattended agent running
in this repo's checkout. **Branch around anything that needs hands on
hardware or a live VM session** -- write it up as deferred in the report,
don't attempt to fake or skip it. Only the CODE-shaped items in FOCUS.md's
"Now"/"Deferred" lists (the STT pipeline scripts, the watchdog/liveness
tooling, firmware-shaped work, a video-wrapper prototype) are in scope for
an unattended run.

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
`[needs VM test]` precisely because they can't be verified from here;
don't upgrade that marker to "done" without an actual live-VM
confirmation from the human.

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
