---
description: Nightly thorough pass on the crt voice console -- code-shaped backlog only, scoped by the GitHub issue backlog
---

<!-- Adapted from scheduler/examples/nightly-batch.md.template and the
     home-assistant project's own no-tracker variant. The backlog moved to
     GitHub issues on 2026-08-14 (hf7y/scheduler#66, hf7y/realisateur#230).
     The retired coordination files were deleted outright by
     hf7y/realisateur#293; there is no file backlog to read. -->

Read the open issues first: `gh issue list -R hf7y/crt --limit 100`.
Everything below is scoped BY that backlog -- if something looks like an
easy win but isn't in service of an open issue, note it as deferred on
the relevant issue; do not implement it just because it's sitting there.

This project is a physical voice console. As of 2026-07-23, `potato` (a
Raspberry Pi, real hardware) is the actual live console, same role
`dexter`/`crt-vm` used to play (that combo is now legacy -- see
`.claude/SESSION-STATE.md`'s 2026-07-23 section for the full topology).
`ssh potato` needs a `Host potato` alias -- present on mandark's
`~/.ssh/config`, confirmed ABSENT on monkey's 2026-08-29. Box-specific,
not account-wide: check `ssh -o BatchMode=yes potato true` before
relying on it. **When it resolves, real STT-pipeline/audio work on
potato IS in scope for an unattended run** -- it is NOT "needs hands on
hardware" just because it's a remote physical box, same as `ssh crt-vm`
access made VM-side work in scope before it. Concretely in scope via
SSH: running/reading `~/.crt/*.log` on potato, restarting a tmux window
there with a fixed env var, deploying an updated script (`scp` +
diff-verify, per `.claude/SESSION-STATE.md`'s "always diff after
scp'ing" note), running `bin/crt-earcon-loopback-test.py` there and
reading its output. Still out of scope: anything needing a HUMAN
physically present (confirming a sound was heard, plugging in a cable,
a 3D print, wiring a hookswitch) -- the loopback test's measurement is
evidence, not proof; say where it still needs Zach's own ear, don't
call it verified-done on the numbers alone. If `ssh potato` fails (host
key, auth, connection, no alias here) treat it like the crt-vm-access
failure policy below: don't spend the cycle debugging it, note it on
the issue, move on.

## 1. Orient

`git log --oneline -10`, current branch state, `README.md`, `HANDOFF.md`
(persistent state/access notes -- trust it over assumptions), `AUDIO-DEBUG.md`,
and the open issues. If the previous nightly run left work in progress,
check open PRs/branches and the relevant issue's own comments for where it
stopped, rather than starting over. (Not `~/reports/crt/` -- unused since
2026-08-06, superseded by issue comments.)

## 2. Re-verify anything a previous run claimed was working

Do not trust a prior run's own claims. For any script/tool a previous
cycle said it "finished," re-read it and check it against its issue's
actual acceptance bar -- most items here are explicitly marked
`[needs VM test]`/needs a live human ear precisely because they can't be
fully verified from here; don't upgrade that marker to "done" without
either an actual live confirmation from the human, OR (2026-07-23) a
concrete measurement from a tool built for exactly that (e.g.
`bin/crt-earcon-loopback-test.py`'s acoustic detection) -- a strong
measurement is real evidence and worth acting on, but still note on the
issue where it stops short of Zach's own ear as final confirmation.

## 3. Push forward on whatever IS in scope per the open issues

Real progress, not just re-reading the same status. Commit as you
complete meaningful chunks -- don't save it all for one giant commit at
the end. If a task needs the user's own hands (plugging something in, a
live VM session, a physical test), do not attempt to route around it --
say so on the issue, with the specific blocker and exactly what's needed
from them.

## 4. Stress-test what you touched

Read through the change once more for the failure modes this project
actually has (stale/flatlined audio capture, a second reader starving the
first, a control-file race) rather than declaring victory on the code
compiling/parsing.

## 5. Report only through issues, never a file

No nightly report file: standing rules forbid writing new prose files, and
in practice none has landed at `~/reports/crt/` since 2026-08-06 while the
real record has kept being merged PRs and closed/commented issues.

**File findings and questions as GitHub issues** -- `gh issue create -R
hf7y/crt` -- not as a file in this repo. The `> ` inline-reply convention
retired with the file backlog on 2026-08-14; Zach answers by commenting on
the issue and leaving it open.

## 6. Before finishing

Confirm every meaningful change has a real commit on a BRANCH, pushed to
`origin` (`hf7y/crt` on GitHub), with a pull request open. `main` is
protected -- never push to it. An overnight run that isn't saved anywhere
didn't happen.
