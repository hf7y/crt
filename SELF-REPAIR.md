# Self-repair — potato's nightly autonomous pass

Scoped 2026-07-22 with Zach. This is `potato`-specific (the Raspberry Pi at
192.168.0.45, replacing dexter/crt-vm as the migration target — see
`vault:crt/COMPUTE-STICK-MIGRATION.md` and the potato memory in the assistant's own
memory store). Not yet mirrored onto crt-vm/dexter.

## What "self-repair" means here (Zach's answers, verbatim scope)

- **Fully autonomous self-editing** — potato's `claude` instance may edit
  its own scripts/configs live, without a human reviewing each change
  first. This is a real escalation from `--permission-mode acceptEdits`
  (the crt-vm default) to `bypassPermissions` (already set via
  `CRT_CLAUDE_ARGS` in potato's `~/.bash_profile`, 2026-07-22).
- **Trigger: nightly**, scheduled — same shape as the existing
  `/nightly-batch` skill (`.claude/commands/nightly-batch.md`), not
  event-driven or continuously running.
- **Sensitivity target: STT/audio first** (`CRT_VAD_THRESHOLD`,
  `CRT_VAD_START_CHUNKS`, `CRT_VAD_TRAIL`, `CRT_VAD_MAX/MIN`,
  `CRT_VAD_PREROLL` — see `bin/crt-stt-solo.py`'s own env-var block — plus
  the STT_GATE/STT_CONFIDENCE knobs in `vault:crt/STT-GATE.md`/`STT-CONFIDENCE.md`),
  but Zach's explicit instruction: **"maximally aggressive as long as it
  uses git right"** — read as license to tune broadly, not just audio,
  provided the git-commit discipline below is never skipped.
- **Safety rail: commit + surface, not approval-gated.** Every change
  must land as a git commit (so revert is always one `git revert`/`git
  reset` away — this is the actual point, per Zach: "I just want that
  autonomous unit to be able to revert any major changes"). Zach
  explicitly deferred the "surface a summary" half (push to a
  service-user-owned remote, reporting) to the service-user setup —
  see "Not yet built" below.

## What's built tonight

- `~/crt` on potato is its own local git repo (`git init`, not connected
  to mandark's remote yet — see "Not yet built"). First commit is the
  as-deployed snapshot, the revert baseline.
- `bin/crt-self-repair.sh` — the nightly wrapper. Does NOT trust the
  `claude -p` invocation to remember to commit: it force-commits
  before AND after the run regardless of what Claude itself did, so a
  crash/timeout mid-run still leaves a clean revertible history. Logs to
  `~/reports/crt-self-repair/<date>.log` on potato itself (not yet synced
  anywhere off-box — see below).
- `systemd/crt-self-repair.timer`/`.service` — nightly, potato-only unit.
  Not installed by `install.sh` (that script is shared with crt-vm, which
  does NOT get this treatment yet) — install by hand on potato:
  `sudo cp systemd/crt-self-repair.{service,timer} /etc/systemd/system/ &&
  sudo systemctl enable --now crt-self-repair.timer`.

## Not yet built (tonight was explicitly base-level only)

- **Any off-box visibility into what potato changed.** Commits are
  currently local-only. Zach: "we have the existing /srv/ situation to
  make that possible, though not sure if ssh is a blocker... save this
  for the service user" — i.e. the actual surfacing mechanism is designed
  together with the service-user work (goal 2 of tonight's ask), not
  built yet. Until that lands, reviewing potato's self-edits means SSHing
  in and reading `git log`/the report log directly.
- **Push access anywhere.** Potato's git repo has no remote configured.
  Explicitly scoped as a separate, bigger decision from local revert —
  see the assistant's own reasoning in-session: local revert doesn't need
  push access at all; push access is a shared-repo blast-radius question,
  deliberately deferred to the service-user identity (modeled on
  `svc-vaporwave`, see `HANDOFF.md`), likely pull-only at first per Zach's
  "right now maybe it's just pull."
- **Any tuning of the actual VAD/gate numbers.** Tonight only wires the
  mechanism (nightly trigger + forced-commit safety net) — the directive
  text handed to `claude -p` each night is what actually does the tuning
  work, and it hasn't run yet (potato was unreachable — mid-physical-move
  — for the rest of this session).
- **Mirroring any of this onto crt-vm/dexter.** Explicitly potato-only for
  now.

## Directive text (what the nightly `claude -p` run is actually told)

See `bin/crt-self-repair.sh`'s own `PROMPT=` variable — kept in the script
itself, not duplicated here, so there's exactly one place to edit it.
