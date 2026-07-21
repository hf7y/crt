**Unrelated side task in progress, not STT work**: an Intel Compute Stick
(STK1AW32SC) migration — flashing/preseeding a USB installer for Debian.
Full details, current status, and next steps in
`COMPUTE-STICK-MIGRATION.md` (project root). If a diagnostic/install boot
was mid-flight when this session ended, that doc says exactly where to
pick up.

# Session state (read this first, before STT-MECHANISM.md)

Last updated: 2026-07-20 night — first session this project had real
dexter+crt-vm network access. Live blocker-clearing pass, not design work.
See `HANDOFF.md`'s "What's actually running right now" section for the
current accurate live layout (it's kept in sync with reality now, not this
file's older waves below).

## Sixth wave (2026-07-20): live access, real bugs found and fixed on hardware
- **VM deploy gap closed**: the VM's `~/crt` (no git, plain deploy target)
  was ~a day behind this repo; nothing from waves 1-5 had ever been
  deployed. New `bin/crt-sync-vm.sh` (status/pull/push, sha256 diff +
  tar-over-ssh, no rsync on either box) replaces manual diffing. Policy:
  safe to overwrite the VM, never dexter; always `pull` VM-only work first.
  Recovered 4 files that only ever existed on the VM (`stt-fixups.json` —
  real confirmed STT mis-hear mappings — plus 3 prototype scripts) before
  the first push.
- **VM hardware-check timer**: installed and *actually verified* (not just
  written) — ran the real offline test suite against real ALSA/tmux on
  crt-vm (126+ checks, all green), confirmed earcons/TTS/sideband all exit
  0 on real hardware. Reworked to a plain script
  (`bin/crt-vm-hardware-check.sh`), not a `claude -p` call — Zach's
  question ("can't this be done without claude?") was right, every check
  is mechanical.
- **OctoPrint confirmed reachable** at `192.168.0.43` (HTTP 302, alive).
- **Real STT pipeline bug found and fixed live**: `stt-feed.sh` was
  silently discarding every utterance after capture (pipefail + arecord's
  expected SIGPIPE on VAD cutoff made the whole pipeline register as
  "failed" even though sox succeeded) — see `HANDOFF.md` for the full
  mechanism. This was likely broken for a while; nobody could tell because
  it failed silently with no error output anywhere.
- **A real regression found and permanently fixed**: the previous
  session's hand-assembled live layout (single-reader `crt-stt-solo.py` +
  `crt-claude-bridge.py` + `crt-monologue.py` pretty-print dialogue pane,
  window 1) worked great for an evening, was never wired into
  `bin/crt-console.sh`, and got silently clobbered by a routine VM reboot.
  Now wired directly into `crt-console.sh`'s own code (not just
  documented) so a future respawn can't lose it again. **Still open**: a
  visual signal of the USER's own speech in window 1 (currently only shows
  claude's replies) — flagged, not built.
- **`bin/crt-levels.sh` missing exec bit** (never worked, unrelated to any
  reboot) — fixed.
- Full VM power-cycle (`VBoxManage controlvm crt-vm poweroff` + `startvm
  --type gui`) was needed at one point — a guest-level `reboot` alone
  doesn't re-establish VirtualBox's audio/USB device bindings, since those
  attach at VM power-on, not guest boot. Worth remembering for the MIDI
  blocker too (`VBoxManage usbattach` "busy with a previous request").

Older waves below are historical record from prior sessions, kept for
context — not all still accurate against current `HANDOFF.md`.

---

Previously last updated: 2026-07-19 night, still no live VM/mic access all session —
no new STT transcriptions came in, so no new error-pattern learning this
session; see `STT-MECHANISM.md` + `~/.crt/stt.log` for that work, still
the standing top priority per `CLAUDE.md`. First commit of this session's
work (`cef8fd1`) is pushed to `origin` (a local bare repo — pushing it
didn't need network, unlike dexter/VM access which this session never had).
A second wave of work (persona-channel mechanism, the secretary wrapper)
happened after that push and is **NOT yet committed** — check `git status`
next session before assuming it's saved anywhere but the working tree.

## What this session did
Chris asked for: (1) an "idle bait" workflow — job reports/blockers
surfaced through the day as cute, low-friction hooks, never naggy enough
he'd turn the TV off, interacted with by picking up the handset; (2)
continued STT refinement (none to do this session — no live traffic);
(3) more expressive earpiece/computer beeps; (4) sidetone investigation;
(5) deeper philosophy digging; (6) keep generating tasks/CAD/RFPs, don't
run dry. All design + scaffolding, **nothing hardware-verified** (no VM
access this session).

## New docs (read these for the actual designs)
- `IDLE-BAIT.md` — the core workflow: report/question sources -> on-screen
  teaser -> earcon (rate-limited, one-shot per item, no nagging) -> pickup
  -> secretary answers by voice. This is the design Chris's mid-session
  note ("cute idle bait... never annoying... he'd turn the TV off")
  directly shaped — that line is close to load-bearing, re-read it if a
  future change threatens to make this feel like a notification badge.
- `SIDETONE.md` — what sidetone is, why it's actually an STT-accuracy
  lever (not cosmetic — ties to VAD-clipping/denoise-distortion failure
  modes in `STT-MECHANISM.md`), and a real open question it surfaced (see
  below).
- `PHILOSOPHY.md` — seven named principles (answer-first-be-right-later,
  cost-of-ignoring-near-zero, restraint-as-trust, verbs-not-menus,
  one-body-several-selves, imperfection-as-character, local-first) plus
  open threads at the bottom worth revisiting.
- `RFP-GALLERY.md`, `RFP-PAYPHONE.md` — design briefs for the two
  gallery/art installation ideas in `PARKING-LOT.md`, fleshed out enough
  to hand to a collaborator. **Payphone brief has a real legal-risk
  section** (real-money payout = gambling device in most jurisdictions) —
  read that before anyone gets excited about the coin mechanism.
- `cad/CAD-BACKLOG.md` — full inventory of printed parts, existing +
  speculative, with what's blocked on what.

## New scripts (all untested against real hardware/audio)
- `bin/crt-earcon.sh` — five tones (bait/question/success/ack/oops) via
  sox synth, routed through the same device logic as `crt-tts.py`
  (dexter bridge for tv/handset, local aplay otherwise).
- `bin/crt-report.sh` — writes `~/reports/crt/LATEST.md` in the
  scheduler's exact shape (see `Project Archive/scheduler`) from inside
  this interactive session, so idle-bait has real content before crt's
  registered-but-dormant nightly Tier 2 batch ever runs. **Already used
  once this session** — `~/reports/crt/2026-07-19.md` has a real entry.
- `bin/crt-idle-teaser.sh` — polling watcher, turns new report/question
  lines into one `crt-think.sh` teaser + (judgment calls only) one earcon.
  Deliberately a separate process from `crt-monologue.sh`, not merged in —
  see `PHILOSOPHY.md`'s open thread on narration vs. restraint.
- `bin/crt-announce.sh` — **bugfix**: was still passing an old `plughw:*`
  guess as the TV device; `crt-tts.py`'s dexter bridge (confirmed working
  via live human test per its own header) expects the literal string
  `"tv"`. Fixed.
- `cad/ir_blaster_mount.scad`, `cad/earcon_grille.scad` — new speculative
  parts, no measurements, see `cad/CAD-BACKLOG.md`.

## Open questions logged (`.claude/QUESTIONS.md`, need Chris)
1. **Is the handset earpiece guest-local ALSA or only host-bridged via
   dexter?** Blocks whether software sidetone is even possible — see
   `SIDETONE.md`. `crt-tts.py`'s `DEXTER_DEVICES` now includes `"handset"`
   alongside `"tv"`, which is a real architecture drift from
   `AUDIO-ROUTING.md`'s original assumption (handset stays guest-local).
   Worth resolving early since it also affects the hardware-sidetone
   recommendation (design the mic/earpiece wiring with a passive tap from
   the start, per `SIDETONE.md` option 1).
2. **Idle-bait quiet hours** — what hours should the earcon go silent?

## Second wave, after the first push (uncommitted)
- `PERSONA-CHANNEL.md` — decided the persona-channel indicator mechanism
  (`cad/CAD-BACKLOG.md`'s open item): a real detented rotary switch Chris
  turns by hand, not a servo/LED display — control and indicator are the
  same object, can't desync, works unpowered. Still needs a specific
  switch part sourced before the faceplate CAD can be drawn.
- `bin/crt-secretary.py` — first real implementation of the secretary
  wrapper (`SECRETARY.md` steps 1-4). Local-answer path ("what's up" reads
  `~/reports/crt/LATEST.md` + `QUESTIONS.md` directly, no Claude call)
  tested standalone and works. Claude-routing path (tmux send-keys + poll
  capture-pane for idle) is an **untested heuristic** — flagged as the
  riskiest part of the design, needs a live session to tune.
  **Not wired into `stt-feed.sh` yet** — that still does raw send-keys.
- `bin/crt-print.sh` + `bin/crt-print-render.py` — text-to-image-to-printer
  path for the secretary's "print full detail" option, wrapping the
  already-installed `catprint` tool. Render tested locally (produces a
  correct PNG); the actual `catprint` invocation/device flag and the
  384px Phomemo head-width guess are unverified against a real printer.

## Third wave: offline-only pass (predictive text, tests, tone taxonomy)
Explicitly scoped to "what we can do without dexter" — all genuinely
offline-buildable/testable, unlike waves 1-2's mostly-design docs:
- **Terminal-size auto-detect** (`crt-pager.py`, `crt-monologue.sh`) — was
  hardcoded 40x15, now env override > real terminal size > hardware
  fallback, so a resized VM window or running on a different machine
  renders correctly instead of silently assuming the wrong geometry.
- **`tests/`** — a real offline test suite, first one this project has had:
  `run_tests.sh` runs shell-syntax checks on all of `bin/*.sh`,
  `crt-pager.py`'s wrap/render/detect_size logic, `crt-monologue.sh`'s
  width-resolution precedence, and `crt-predict.py`'s model/guess logic.
  **All green right now** (`bash tests/run_tests.sh`) — rerun after any
  future change to those files, this is real regression coverage, not
  aspirational.
- **`bin/crt-predict.py` + wiring into `crt-stt-solo.py`** — resolves a
  TODO that was already sitting in `crt-stt-solo.py`'s source. Cheap
  whole-utterance + bigram frequency model over `~/.crt/stt.log`
  (hour-of-day bucketed), flashes a guess the instant an utterance ends,
  before whisper has run — `emit()` already unconditionally overwrites the
  flash with the real transcription once whisper returns, so this was a
  small, safe addition. **Opt-in** (`CRT_PREDICT_FLASH=1`), off by
  default — nobody's heard/seen it live yet, and a wrong guess flashing
  needs a human judgment call on whether it reads as charming or
  confusing (see `PHILOSOPHY.md` #6). Model needs `crt-predict.py build`
  run against a real `stt.log` before it has anything to guess from — untested
  against real transcript history, only against synthetic data in
  `tests/test_predict.py`.
- **`EXPRESSIVE-TONE.md`** — a register taxonomy (clipped/urgent,
  warm/curious, content/settled, wistful/quiet, public/announcement)
  mapping fade-out length + pitch contour (audio) and line brevity (text)
  to the same emotional dial. Implemented as `CRT_EARCON_FADE_SCALE` in
  `crt-earcon.sh` (one dial scales every tone's fade-out) plus two new
  contours, `curious` and `content`. All 7 tones × 3 fade scales
  synth-tested this session (sox renders clean); still unheard by a human.

## Fourth wave: vision + scheduler wiring, then ramped down
`DEVELOPMENT-WORKFLOW.md` ties everything into a three-tier autonomy model
(mandark disposable-clone batch / new VM-resident hardware check / this
kind of interactive session). New this wave: `VM-JOBS.md` +
`.claude/commands/vm-hardware-check.md` + `systemd/crt-vm-hardware-check.
{service,timer}` (not installed, no VM access) + `bin/crt-sync-vm-reports.
sh` (pull-based, untested). **Real scheduler wiring done**: `schedule/
crt.conf` (outside this repo, in Project Archive/scheduler) now has a
`DEPLOY_FRESH_CMD`/`DEPLOY_CMD` pair surfacing a stale/missing VM-report
sync in the daily `morning-report.sh` aggregate — verified the probe
itself runs correctly in isolation. Also: `SUPERVISOR.md` +
`crt-secretary.py` refactored to a playbook registry (status/run_tests/
what_time, 10 tests), `HOOKSWITCH.md` + a real debounce fix (was a genuine
bug, no hardware needed to find or fix it), `DISPLAY-CALIBRATION.md` +
`crt-calibrate-display.py` (overscan safe-margin game, 15 tests),
`SIDEBAND.md` + `crt-sideband.sh` (ambient presence tone, 8 tests). Test
suite is now 56 checks, all green (`bash tests/run_tests.sh`).
**Explicitly stopped here on the user's instruction** ("ramp this down")
rather than continuing to expand scope.

## Fifth wave: "full steam" — all 8 offline-safe FOCUS.md items shipped
User asked to work through everything buildable without VM/dexter access,
self-pacing usage (no live usage-% tool available, so paced by chunking +
frequent commits instead). All landed, tested, committed, pushed:
`fa31856`/`082db9e`/`7fde922`/`16c816b`/`ae639b6` (see git log for exact
diffs) —
1. `stt-feed.sh` routes through `crt-secretary.py` when `CRT_SECRETARY=1`
   (default off).
2. `crt-pager.py`/`crt-monologue.sh` now consume `~/.crt/display.conf`'s
   safe margin.
3. `crt-earcon.sh`'s `bait`/`curious`/`question`/`content` are continuous
   glissando sweeps now, not stepped notes.
4. `crt-idle-teaser.sh` teaser lines carry an ANSI color per register into
   `thoughts.log`.
5. `crt-tts.py` has `--mood`/`--pitch-semitones`/`--rate-mult`/
   `--volume-mult`, applied via a sox post-process step (works for both
   backends despite neither having a native pitch knob for this).
6. Sideband state transitions wired: `crt-stt-solo.py` opt-in
   (`CRT_SIDEBAND=1`) listening/thinking; `crt-tts.py`/`crt-earcon.sh`
   always-on mute-duck (inert unless `crt-sideband.sh` is running).
7. `crt-secretary.py` gained a `calibrate` playbook (single-shot pattern
   render only, not the interactive game).
8. Claude-fallthrough requests now log to `~/.crt/fallthrough.log`.

Test suite grew from 76 to **126 checks**, still all green. `FOCUS.md`'s
offline-safe section marked DONE — nothing left there for an unattended
pass until a new batch gets registered. A recurring cron
(`092c9b41`, every 3h, session-only/expires in 7 days) checks
`BLOCKERS.md`'s crt section for anything you've cleared and reports back
— it does not resolve/delete entries itself.

## Not done / explicitly out of scope this session
- Nothing hardware-verified (no VM/mic/audio access this session at all —
  pure design + scaffolding).
- The secretary wrapper itself (`SECRETARY.md` steps 1-4) — still the
  actual next concrete build once someone's back on the VM; idle-bait is
  the lure toward it, not a replacement for it.
- No STT error-pattern learning (no live transcriptions this session).

## Pick up next, in order
1. Get back on `crt-vm` and answer question #1 above — it gates both
   sidetone and whether `crt-idle-teaser.sh`'s earcon calls will even
   reach the handset correctly.
2. Smoke-test `crt-earcon.sh`'s five tones by ear (nobody has heard them).
3. Run `crt-report.sh` + `crt-idle-teaser.sh` live for a day, see if the
   teaser cadence actually feels like bait or like a nag — this is a
   judgment call only a live test can settle, not more design.
4. Keep building the secretary wrapper (`SECRETARY.md`) — the actual
   payoff once idle-bait gets someone to pick up.
