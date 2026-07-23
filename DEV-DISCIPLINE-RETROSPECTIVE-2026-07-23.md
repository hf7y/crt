# Dev-discipline retrospective — crt (2026-07-19 → 07-23)

Audit of the first ~4 days of `crt` (186 commits) to name what
recurred, what it cost, and the specific disciplines to adopt so the
build/deploy process gets cleaner and more stable. Cite-first, terse —
same house style as `ARCHITECTURE-REVIEW-2026-07-23.md` /
`REFACTOR-ASSESSMENT.md`, which this builds on.

Bias note: this is a practices retro, not a design review. Where I
give an opinion it's flagged as one.

---

## The one-sentence finding

**The dominant failure mode is silent failure**, and the second is
**layering-not-replacing** — and both were fought *reactively*,
one incident at a time, instead of being closed off systemically. The
instincts are right; they aren't yet installed as defaults.

---

## What the numbers say

- **186 commits in ~4 days.** Distribution: 18 / 28 / **90** / 13 / 37.
  The Jul-21 spike (90) is a single-day burst — the same day four bugs
  came out of one "happy-path audit" (`3f48046`, `b05aa6f`).
- **60 of 186 commits (32%) landed 00:00–06:00.** Late-night is where
  the silent-failure bugs cluster (`136a812` 22:23, `17cacd9` 21:57,
  the 05:39 sync-truncation fix `8088cfa`). Fatigue and
  fail-quietly are compounding each other.
- **Test files grew 0 → 44** (16 by day 2, 36 by day 3). Testing
  discipline is real and improving — see "What went right."
- **43 tracked `.md` files** vs. the code they describe; ~20 are design
  docs for unbuilt features (`REFACTOR-ASSESSMENT.md:122-128`).

---

## Failure pattern 1 — silent failure (the through-line)

Code that fails with **exit 0 / no output / a healthy-looking status**,
found only by accident long after breaking. Every instance below was
live-broken for an *unknown* duration:

- `stt-feed.sh` — `set -o pipefail` + `arecord`'s SIGPIPE made every
  utterance register as a failed pipeline; **every utterance silently
  discarded before whisper ran**, no error anywhere (`136a812`;
  `HANDOFF.md:133-143`).
- Capture default `plughw:0,0` doesn't exist on potato → process exits
  silently, "live and broken for an unknown period"
  (`ARCHITECTURE-REVIEW-2026-07-23.md:145-149`).
- Earcons POSTed to a dexter server with no potato equivalent → silent
  no-op, exit 0, "root cause of 'no beeps ever' for potentially a long
  time" (`:150-154`).
- `crt-sync-vm.sh` pull **silently truncating** (`8088cfa`).
- Silent stdin-reader death; unguarded `thoughts.log` write
  (`3f48046`, `b817b39`).
- Missing exec bits → panes "silently failed to launch," masked while a
  feature flag was off (`17cacd9`, `873d771`).
- A hung scanner process where "every health check reported it as fine"
  — produced a **false 'confirmed working' claim** (`HANDOFF.md:194-214`).

Cost: debugging by archaeology (`ps aux`, a surviving log file, an
import crash) instead of by alarm.

---

## Failure pattern 2 — build-but-don't-wire

Components finished, tested, then left disconnected from the thing they
were built to serve — so a reboot or a fresh session runs the *old*
path as if the work never happened.

- The canonical incident: a better tmux STT layout ran well for a full
  evening but was "never wired into `crt-console.sh`" → a routine reboot
  respawned the old default and "the better setup was gone with no
  record beyond `ps aux` archaeology" (`HANDOFF.md:123-132`). The lesson
  the doc itself draws: **"a doc is easy to skip, code that runs on
  every boot isn't."**
- `crt-calibrate-display.py` — "built + tested, not yet wired into what
  it's supposed to protect" (`DEVELOPMENT-WORKFLOW.md:40-43`).
- `crt-wake-arm.py`, secretary sink, speculative response, media player,
  `crt-pager.py` — all built, all parked behind default-off flags
  pending live verification (`PARKING-LOT.md:185-243`, `HANDOFF.md:279-281`).

Right now the working tree has **untracked, finished-looking work never
committed**: `bin/crt-self-repair.sh`, `bin/mandark-whisper-server.py`,
`bin/setup-mandark-whisper-persistence.sh`, plus their systemd units.
Same pattern, one step earlier in the pipe.

---

## Failure pattern 3 — layering instead of replacing

Three sessions each concluded "the wake mechanism isn't good enough" and
**added another layer** rather than replacing the one under it →
"five distinct matching mechanisms... most of which has never been
exercised together in one live run" (`ARCHITECTURE-REVIEW-2026-07-23.md:95-105`).
The wake state machine was "referenced by name in its own code and log,
but implemented nowhere" (`:66-71`). This is scope creep disguised as
progress: each layer is real work that increased complexity without
retiring anything.

Config sprawl is the same disease in data form: port 8993 hardcoded in
3+ files *and colliding* with the scanner; `plughw` indices (including
the known-broken `0,0`) scattered across six files
(`REFACTOR-ASSESSMENT.md:52-70`).

---

## Failure pattern 4 — deploy by hand-copy loses work

Deploy targets are **not git clones**. potato's tree is "seeded by
hand-copying files over SSH," separate git history; VM→mandark moved by
"scp/ssh pipe by hand" (`ARCHITECTURE-REVIEW-2026-07-23.md:39-42`,
`HANDOFF.md:66-70`). Consequences, all live-observed:

- The wake-judge system "never carried forward to potato — discovered
  only because its own log file happened to survive."
- `crt-wake-pool.py` "had simply never been copied to potato's bin/ at
  all, discovered only when a new script tried to import it and crashed."
- potato had "real independent commits... never synced back... until
  this session found and cherry-picked them."
- Root cause: "nothing verifies that potato's deployed state matches any
  particular commit... or flags drift" (`:178-195`).

---

## Failure pattern 5 — secrets sitting in the open

- **A plaintext VM password is committed in a tracked file:**
  `HANDOFF.md:56` (`Password kw0kWXESrKQpNvuKXiU8`, passwordless sudo).
  It's in git history — rotating the password is the only real fix;
  deleting the line doesn't un-leak it.
- `crt-vm_claude_creds.json` sits **untracked** in the tree (not leaked
  to git, but loose and one `git add -A` away from it).
- A `raspios_lite_arm64.img.xz` disk image and `BOOTIA32.EFI` are loose
  in `cad/` — build debris, not source.

Partial credit: the `svc-vaporwave` restricted service identity was the
right instinct (`HANDOFF.md:78-99`).

---

## What went right (keep doing these)

Don't over-correct — several disciplines here are genuinely good and
should be the *model* for closing the gaps above:

1. **Mechanical enforcement over reminders.** The CRT-color rule is a
   test (`test_no_primary_rgb_codes_in_palette`), not a comment; the
   window-1 marker is "a mechanical filter, not a style reminder"
   (`CLAUDE.md:81-117`). This is exactly the right answer to
   silent-failure — apply it wider.
2. **Boot-path code over docs**, learned from the reboot regression.
3. **Force-commit before AND after autonomous runs** so a mid-run crash
   still leaves revertible history (`SELF-REPAIR.md:35-44`).
4. **A watchdog aimed at the silent-death class** — `crt-vm-watchdog.sh`
   checks each pane's process every 5 min, and deliberately does *not*
   auto-respawn the brain so a dead one stays visible (`HANDOFF.md:223-242`).
5. **The "verify live, not exit-code" distinction** is named repeatedly
   and honestly (TTS "smoke-tested (exit 0)... not yet confirmed audible",
   `HANDOFF.md:272-274`). The vocabulary exists; it needs teeth.
6. **Honest retro docs.** This audit was easy *because* the project
   already writes clear-eyed reviews. That habit is an asset.

---

## The disciplines to introduce

Ordered by leverage. Each targets a pattern above and is stated as a
mechanical rule, not an aspiration — because §"What went right" shows
mechanical rules are the ones you actually keep.

### 1. Fail loud by default (kills pattern 1)
- **No silent no-op path.** Any device open, HTTP POST, or subprocess
  whose failure currently means "nothing happens" must log a WARN and,
  where safe, exit non-zero. Add a `test_shell_syntax.sh`-style sweep
  that greps for `pipefail` + pipes-into-`arecord`/`sox` and for POSTs
  to a hardcoded host, and fails CI.
- **`set -euo pipefail` audit**: the `stt-feed.sh` bug was pipefail used
  *without* understanding SIGPIPE. Every pipeline that can legitimately
  SIGPIPE needs an explicit guard, tested.
- **"Confirmed working" is a banned phrase without a witness.** A claim
  of working requires either a test name or a human-sense verification
  ("heard it", "saw it on the tube") in the same commit message. Exit 0
  is never sufficient — the hung-scanner incident is the proof.

### 2. Wire-on-commit; nothing lands parked (kills pattern 2)
- A component isn't "done" until something *runs it on the real path* —
  boot script, timer, or an enabled flag. If it must ship behind a
  default-off flag, the commit adds a tracking entry AND a test that the
  flag path executes.
- **Pre-commit clean-tree check.** Untracked `bin/*.py`/`*.sh` older than
  the current session is a smell; either commit or delete. (Three such
  files are loose right now.)

### 3. One source of truth for config (kills pattern 3's data half)
- Adopt `REFACTOR-ASSESSMENT.md:52-82`'s fail-loud config module: one
  place defines port 8993, device indices, hostnames; shell/Python/systemd
  read from it. Keep Zach's rule — never drop a hardcoded override, add
  name-resolution *alongside*. Delete the `plughw:0,0` default everywhere.

### 4. "Replace, don't layer" as a design gate (kills pattern 3's code half)
- Before adding a mechanism that overlaps an existing one, the commit
  message must name what it **retires**. If it retires nothing, that's a
  flag to stop and consolidate first. Five wake mechanisms is the warning.

### 5. Make deploy a verifiable git operation (kills pattern 4)
- Even without full CI: potato/VM trees should be clones, and a
  `crt-deploy-check` script should compare deployed HEAD against origin
  and **fail loud on drift** — the exact thing "nothing currently
  verifies" today. This alone would have caught three lost-work incidents.

### 6. Secrets hygiene (kills pattern 5) — do this first, it's a real leak
- **Rotate the VM password now** (`HANDOFF.md:56`); it's in history.
- Add `*creds*.json`, `*.img.xz`, `*.EFI` to `.gitignore`; move real
  secrets to an untracked `.env`/`secrets/` referenced by the config
  module in #3.
- A pre-commit `git secrets`-style grep for high-entropy strings.

### 7. Cadence guard (addresses the 32%-after-midnight signal)
- Opinion, not mechanism: the silent-failure bugs cluster in late-night
  bursts. Landing autonomous/self-repair work to `bypassPermissions`
  while tired is the riskiest combination in the repo. Consider gating
  irreversible or deploy-touching commits to daytime, and letting the
  force-commit-revertible batch (`SELF-REPAIR.md`) absorb the rest.

---

## The adoptable checklist (paste into CLAUDE.md when ready)

Before marking anything done:
- [ ] Does it fail **loud**? (no exit-0 no-ops; pipefail+SIGPIPE guarded)
- [ ] Is it **wired to a real path** (boot/timer/enabled-flag), not just built?
- [ ] "Working" claim backed by a **test name or a human-sense witness** — never exit code alone?
- [ ] New mechanism **names what it retires**?
- [ ] Config values read from **one source**, not retyped per file?
- [ ] Deploy verified against a **git ref**, drift fails loud?
- [ ] **No secret** added to a tracked file? Tree clean of debris?
