# Pending writes into `.claude/` — this run was BLOCKED from making them

**Delete this file once the three blocks below are pasted into their real
homes.** It exists only because the 2026-07-29 nightly-batch run could not
write them itself, and a second questions file is exactly the
filed-where-nobody-reads failure this same run diagnosed elsewhere. It is not
a new convention.

## The block, first-hand

`.claude/FOCUS.md`, `.claude/QUESTIONS.md` and `.claude/SESSION-STATE.md` are
classified sensitive by the harness. Every write attempt this run — `Edit`,
`Write`, and a plain `cat >>` through Bash — was refused with
`Claude requested permissions to edit <path> which is a sensitive file`, and an
unattended run has no human present to approve the prompt, so it auto-denies.
Nothing was worked around: routing past a permission guard is not a fix.

`.claude/settings.json` carries no `permissions` block, so this is a built-in
harness guard on `.claude/**`, not a project rule that could be edited here.

**Why this is worse than one blocked run.** `CLAUDE.md` tells every session to
keep `.claude/SESSION-STATE.md` current so a reboot doesn't lose the thread,
and the `nightly-batch` skill is *scoped by* `.claude/FOCUS.md` and told to
append questions to `.claude/QUESTIONS.md`. If unattended runs can no longer
write any of the three, then FOCUS.md rots silently while every run keeps
reading it as current — the file most trusted to be true becomes the one
nothing can correct. Tonight already produced one concrete instance: the
FOCUS.md premise corrected below had been wrong for four days.

**Needs a decision from Zach** (also filed in the report): allow `.claude/**`
writes for this project via a `permissions` entry in `.claude/settings.json`,
or move FOCUS/QUESTIONS/SESSION-STATE out of `.claude/` to the repo root where
runs can maintain them.

---

## 1. `.claude/FOCUS.md` — correction, append under the "the brain moved to dexter, the EARS did not" item

> **CORRECTION 2026-07-29 (nightly-batch, on dexter, first-hand): this item's
> central premise was wrong in two independent ways, and both are now fixed in
> code (`43685e5`).**
> - "`bin/dexter-whisper-server.py` already exists ... so this is a
>   deploy-and-repoint, not a build" — **it does not exist.** `3dee2d5` (the
>   2026-07-24 refactor sweep) deleted it while dexter was legacy; the host
>   policy reversed four days later and this item was filed against a deleted
>   file. It survives only in `~/crt.bak-2026-07-28/bin/` on potato.
> - It was not a deploy in a second way either: **dexter has no Python
>   packaging toolchain.** `python3` is 3.14.4, `python3 -m pip` → no module
>   named pip, `import ensurepip` → ModuleNotFoundError. Needs
>   `sudo apt install python3-venv python3-pip`, and ctranslate2 may have no
>   wheel for 3.14.
> - **Done instead:** one host-agnostic `bin/crt-whisper-server.py`,
>   `bin/mandark-whisper-server.py` reduced to a compat shim (mandark's live
>   unit names that path and could not be reached to edit),
>   `bin/setup-dexter-whisper-persistence.sh` with a preflight that fails loud
>   on each real prerequisite, and `tests/test_whisper_server.py` (12 tests,
>   including a mechanical guard that no host-named server may carry its own
>   `WhisperModel(` call — the duplication that caused this).
> - **Still open, unchanged:** the server is not standing on dexter, and
>   `crt-console.sh:176`'s `CRT_WHISPER_SERVER` default still points at
>   mandark. Repointing it flips a live console default — `[hw]`, do it with
>   the handset in reach.
>
> **SHARED-HOST FOOTPRINT DECLARED (per CLAUDE.md's build discipline):** this
> run installed NOTHING on any host. No unit, no venv, no package, no port. The
> only footprint it would ever create is
> `/etc/systemd/system/crt-whisper-server.service` + `ufw 8991/tcp` on dexter,
> and only if a human runs `bin/setup-dexter-whisper-persistence.sh`. Declared
> here in advance so it is not an undeclared surprise later —
> `notify-senechal` is MISSING on dexter, so it could not be filed the normal
> way.

> **RESOLVED 2026-07-29 (nightly-batch, on dexter): the 3-day silence is over,
> and this run is the witness.** From
> `~/.local/share/scheduler-paced-runner/run.log` on dexter: **465 HOLD lines
> and zero RUN / zero DISPATCH in the log's entire history until 01:00 tonight**
> — dexter had never dispatched anything, ever. Cause was the even-burn gate
> (`usage-gate.sh:237`): a host running one held participant cannot spend, so it
> can never fall below the burn line it is held against. Fixed by scheduler
> `e502555` (`USAGE_RUSH_BEFORE_RESET_MIN=10080`, Zach-directed). The witness is
> one second wide — `01:00:02 PULL fast-forwarded to e502555` →
> `01:00:03 RUN ... rush=True` → `01:00:03 DISPATCH [1/4] crt`.
> `sweep.lock` is confirmed a red herring for the third time (0-byte file;
> `flock` is advisory on the fd, so a leftover file never blocks — this run took
> it cleanly). **`expires_at` is REAL and unresolved: 2026-08-01T01:14, and
> tonight's dispatch did not refresh it.** See QUESTIONS.md.

## 2. `.claude/QUESTIONS.md` — append verbatim

- **2026-07-29 (nightly-batch): the handset 3-pin switch — keep the USB HID
  encoder, or move the switch onto Pi GPIO?** You said this run that the
  scap/STL half is resolved (printed prototype fits) and the 3-pin is the live
  thread, but that you had not looked at the write-up. Reason found: the
  write-up is not a document, it is a section at the bottom of `HOOKSWITCH.md`
  ("Wiring/kill options for the physical switch", `9cc07a1`) — a file you have
  no reason to open. It was never surfaced here. Compressed to the actual fork:
  - **(2) software mute** — what `bin/hookswitch-listen.sh` does *today*:
    switch → USB HID encoder → `pkill -STOP/-CONT`, with debounce. Zero new
    hardware. On-hook silence is a promise from a running process.
  - **(3) Pi GPIO** — same logic, different input layer: switch COM+NO straight
    to header pins, read via `gpiozero`/sysfs. Deletes the USB encoder board.
    `apply_state()`/`debounce_loop()` and their test survive mostly as-is; only
    the parsing layer is rework.
  - **(1) hard-kill** — cut the mic conductor electrically, so on-hook means
    physically deaf. The only option that makes on-hook a *fact* rather than a
    promise, matching that doc's own "resting = actually off" framing. Costs
    real analog work and, alone, kills every soft state.

  **2 and 3 are not rivals — 3 is how 2 gets its raw signal — and 1 can be
  layered underneath either one later as a fail-safe.** So this is really two
  independent yes/nos, both answerable without touching hardware:
  > (a) USB encoder, or move to GPIO? (answer inline here)
  > (b) do you want the hard electrical kill eventually, underneath it?

  Full tradeoffs, unchanged, in `HOOKSWITCH.md`. Next hardware step either way
  is a multimeter continuity check of COM/NO/NC on the actual switch body —
  nothing here can do that.

- **2026-07-29 (nightly-batch, first-hand on dexter): crt's dead-man switch
  trips 2026-08-01 and tonight's successful run did NOT reset it.** Less a
  question than a one-command ask with a deadline.
  `~/.local/share/crt-nightly-batch/expires_at` reads
  `2026-08-01T01:14:14-05:00`; its mtime is still 2026-07-25 01:14 after this
  run dispatched, and `scheduler:3014` re-stamps only when the file is
  *missing*, so nothing crt does on its own will renew it. On Saturday
  `usage-paced-runner.sh:278` starts logging `SKIP crt -- EXPIRED` and crt goes
  dark again — for a reason unrelated to the burn-line deadlock that was just
  fixed, about one week after it started dispatching.
  **This run deliberately did not renew it.** An unattended job clearing its own
  dead-man switch defeats the entire mechanism, so it is escalated rather than
  quietly reset. Renew with, on dexter:
  `rm ~/.local/share/crt-nightly-batch/expires_at`
  > (answer inline here — renew it, or is a hard stop on 08-01 what you want?)

- **2026-07-29 (nightly-batch): unattended runs can no longer write `.claude/`.**
  See the top of this file. Allow it in `.claude/settings.json`, or move
  FOCUS/QUESTIONS/SESSION-STATE to the repo root?
  > (answer inline here)

## 3. `.claude/SESSION-STATE.md` — append

> **2026-07-29 (nightly-batch, ON dexter — the first crt run since 07-25).**
> Landed `43685e5`: one host-agnostic whisper server, mandark's path kept alive
> as a compat shim, a dexter setup script whose preflight encodes real probed
> prerequisites, 12 new tests, suite ALL GREEN. Answered all three BLOCKERS.md
> replies with first-hand dexter evidence (appended, not committed — the ~:30
> autocommit watcher owns that file and `focus-commit` is missing here).
> **Carry forward, in order:** (1) `expires_at` trips 2026-08-01, needs one
> human command; (2) `.claude/**` is write-blocked for unattended runs, so
> FOCUS.md will rot until that is settled; (3) the four ecosystem guard
> commands are still MISSING on dexter (`jq` is now present); (4) the whisper
> server is built but not standing — needs `sudo apt install python3-venv
> python3-pip` on dexter first; (5) `crt-console.sh:176` still points the
> console's ears at mandark.
