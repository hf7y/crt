# crt — focus & backlog

**Current focus: the core STT pipeline** (see "Now (core STT, blocked on
VM)" below) — but every item there needs a live `crt-vm` session, which an
unattended batch run doesn't have. **"Now (offline-safe, no VM/dexter
needed)" is what tonight's actual autonomous work should be**, until VM
access is available again. See `../HANDOFF.md` for full state and access.

## Cross-project ask: locate prior demucs work on dexter (2026-07-20)

`wtul` (the CD-ripper project) needs Demucs for ROADMAP #5 (instrumental
intro/outro detection) and Zach says he already tried installing/running
Demucs on dexter once before, with leftover files somewhere on that
machine. This project runs on dexter/crt-vm and is the thing already
reaching dexter over the network (see `dexter-whisper-server.py`), so it's
the natural place to leave this note for whoever/whatever next has hands
or a session on dexter.
%%ACTION next time there's a live session on dexter (not the isolated
nightly-batch clone — this needs the real machine), look for prior Demucs
install/model-download artifacts (check pip/conda envs, `~/.cache`,
anywhere resembling a `demucs` venv or downloaded checkpoints). Report
findings back — either the path to reuse, or confirmation there's nothing
to reuse — to `wtul`'s `ROADMAP.md` #5 / `.claude/QUESTIONS.md` (the
cross-project scheduler `BLOCKERS.md` has the `## wtul` heading if a
quicker landing spot is wanted instead).

## Now (offline-safe, no VM/dexter needed) — registered 2026-07-20

Every item here is buildable and testable with `tests/run_tests.sh` alone
— no VM, no dexter, no real audio hardware. Each MUST land with its own
test coverage added to `tests/`, and any behavior change to an existing
default pipeline (stt-feed.sh, crt-stt-solo.py) MUST be opt-in via an env
flag, default off, exactly like `CRT_PREDICT_FLASH` already is — none of
this should change what the live console does today until a human can
watch it run. Do NOT claim anything "sounds good," "feels right," or is
hardware-verified — that bar still needs a real ear/eye, see the
acceptance-bar note in `.claude/commands/nightly-batch.md`.

1. **Wire `crt-secretary.py` into `stt-feed.sh`**, opt-in
   (`CRT_SECRETARY=1`, default off — the raw send-keys path stays the
   default). Test with a mocked tmux, same pattern as
   `tests/test_secretary.py`. See `SECRETARY.md`/`SUPERVISOR.md`.
2. **Consume the calibration margin**: `crt-pager.py`/`crt-monologue.sh`
   don't read `~/.crt/display.conf` yet — subtract the saved margins from
   the auto-detected WIDTH/HEIGHT. See `DISPLAY-CALIBRATION.md`'s "not
   done this session" note.
3. **Extend `crt-earcon.sh`'s pitch contours** — most registers are still
   plain note sequences, not the glissando/sweep shapes `oops` already
   uses. See `EXPRESSIVE-TONE.md`'s "explicitly not doing (yet)" list.
4. **ANSI color-per-register** in `crt-idle-teaser.sh`/`crt-monologue.sh`
   output — the color dimension `EXPRESSIVE-TONE.md` named but didn't
   reach. `CLAUDE.md` explicitly grants ANSI control of the screen.
5. **Per-call TTS prosody overrides** in `crt-tts.py` — pitch/rate/volume
   currently only come from flat `tts.conf`/env config, not per-call, so
   the register taxonomy can't actually vary spoken delivery yet. See
   `EXPRESSIVE-TONE.md`.
6. **Wire sideband state transitions**, opt-in — `crt-stt-solo.py` (VAD
   start/stop -> listening/idle), `crt-secretary.py`/`crt-tts.py`/
   `crt-earcon.sh` (mute-duck around their own playback via
   `~/.crt/sideband.mute`). See `SIDEBAND.md`'s "not done this session."
7. **A `calibrate` playbook** in `crt-secretary.py` — voice trigger runs
   `crt-calibrate-display.py show`. Named as the natural next playbook in
   `SUPERVISOR.md`.
8. **Fallthrough-logging** in the supervisor — log any request that
   matches no playbook (to a file, not acted on) so a future session can
   see which requests keep escalating to Claude and are worth a new
   playbook. `SUPERVISOR.md`'s open item.

Stop-by-report-time applies as usual (see nightly-batch.md step 3's
budget). If only some of these fit in one pass, do them in the order
listed — earlier items unblock/inform later ones (2 and 7 are related;
6 depends on nothing else here).

## Now (core STT, blocked on VM)

- **Reliability of detection ("stops detecting" / stale capture)** is the top
  problem. See **`AUDIO-DEBUG.md`** — it enumerates several parallel approaches,
  now partly implemented (all opt-in, none disturbs the working pipeline):
  - A `bin/crt-capture-watchdog.sh` — detects a flatlined capture, re-asserts
    mixer, kills stale readers, optionally bounces the stt window. `[needs VM test]`
  - B `bin/crt-console-solo.sh` + `crt-stt-solo.py CRT_STT_SINK=claude` —
    single-reader console (no dsnoop) so a second reader can't starve capture.
  - C keep-alive (built into the watchdog, `CRT_WD_KEEPALIVE=1`).
  - D `bin/crt-audio-doctor.sh` — `check` / `monitor` liveness telemetry to find
    what the staleness correlates with.
  Next: run A/B/D on `crt-vm`, capture a `~/.crt/liveness.csv`, decide the fix.
  **All of this needs a live crt-vm session — not actionable by an
  unattended batch run right now.**
- The standalone STT view (`bin/crt-stt.sh`) — verify it runs and is useful for
  watching/tuning transcription, decoupled from Claude. **Also needs the VM.**
- Ongoing calibration: `CRT_VAD_THRESHOLD`, Windows mic boost, normalization.
  **Also needs the VM.**

## Deferred (not in current focus — do not pull these into an STT session)

**Moved 2026-07-20**: the hands-on-hardware items that used to live here
(MIDI controller, physical hookswitch, OctoPrint, Benchy print, USB
phone-interface module, the VM-hardware-check install) now live in the
scheduler's cross-project `BLOCKERS.md`, under `## crt` — that file is the
one-glance human-owned surface across every project; this one stays
scoped to code-shaped backlog. Still deliberately **not** in current
focus, still branch around anything needing hands on hardware or a live
VM if it resurfaces here by mistake.

1. **Stretch: video-call wrapper** (Zoom/WhatsApp) over the handset/CRT —
   not a blocker (nothing needed from a human to start), just genuinely
   unstarted backlog, lowest priority.

## Secretary reframing (2026-07-19) — see SECRETARY.md
The real goal is a phone-secretary service, not a raw STT->Claude terminal.
Printer = long output, CRT = short status + slow-scroll (`bin/crt-pager.py`,
built), TTS = spoken confirmation through the phone (`bin/crt-tts.py` +
`bin/crt-tts-calibrate.py`, built + espeak-ng deployed to crt-vm), TV
announcements for Chris rate-limited to 1/15min (`bin/crt-announce.sh`, code
done, cross-VM-boundary bridge to actually reach the TV output NOT built --
see AUDIO-ROUTING.md). `bin/crt-stt-speakback.sh` runs STT in debug mode
(stdout, NOT wired to Claude) and speaks "heard: ..." back through the phone
so a person can debug the mic by ear -- running live on crt-vm's `stt` window
as of 2026-07-19. The actual secretary wrapper (structured request -> Claude
-> route response to printer/CRT/TTS) is still design-only, next concrete step.

## MIDI passthrough (2026-07-19 update)
Root cause found: Windows had the MiniLab's MIDI interface **disabled**
(`CM_PROB_DISABLED` in Device Manager) -- fixed via `Enable-PnpDevice`. But
`VBoxManage usbattach` still fails ("busy with a previous request") even
after that fix and a full VM power-cycle -- points to a stuck VBoxUSB/VBoxSVC
host-proxy state independent of the PnP fix. Next: restart the VBoxSVC
process/VirtualBox host service (blocked this session by the auto-mode
classifier as a process-kill action -- needs the user's direct OK) or a
Windows reboot. Deprioritized per user instruction this session ("abandon
midi... pick it up later") in favor of the TTS/pager/secretary work above.

## faster-whisper network service on dexter (2026-07-19, DONE, live)
`bin/dexter-whisper-server.py` runs faster-whisper natively on dexter's Ryzen
(port 8991, `/health` + `/transcribe`) so transcription isn't CPU-capped by
the VM. `crt-stt-solo.py` uses it when `CRT_WHISPER_SERVER=http://192.168.0.22:8991/transcribe`
is set — verified working live. Not auto-starting yet (manual
`Start-Process` on dexter); add a Scheduled Task next. See project memory for
the VPN/huggingface.co gotcha and how the model got there.

## Ring/pickup detection (2026-07-19, smoke-tested)
`bin/crt-ring.sh <n>` rings the phone via `crt-stt-solo.py` (the sole mic
reader) — warble tone in bursts, checks for voice only in the silent gaps
(avoids the tone false-triggering), stops on pickup, prints a timeout
message on the active screen if unanswered. No physical hookswitch yet, so
"pickup" is inferred from voice activity alone.

## Inner monologue / on-screen narration (2026-07-19, DONE, live)
`bin/crt-think.sh "text"` appends a timestamped line to `~/.crt/thoughts.log`;
`bin/crt-monologue.sh` tails it on-screen, word-wrapped, in first person as
the machine narrating itself ("i'm a crt, i have a handset..."). This is now
the CRT's active tmux window (STT moved to a background window, still
running/speaking, just not what's displayed). **Ongoing practice going
forward: narrate real work into this log in-character as it happens** (via
`crt-think.sh` over SSH) rather than only reporting after the fact — it
doubles as a durable append-only context record for later sessions.

## Offline test suite now exists (2026-07-19)
`tests/run_tests.sh` — shell syntax checks, `crt-pager.py`/`crt-monologue.sh`
width logic, `crt-predict.py` model logic. Zero VM/hardware needed. Any
future nightly-batch pass should run this before claiming a code-shaped
change "done" — it's real regression coverage now, not just an acceptance-
bar reminder.

## Idle-bait / beeps / sidetone / philosophy design pass (2026-07-19)
Design session, no VM access. Full detail in `.claude/SESSION-STATE.md`
(read that first next session) and the new top-level docs it lists
(`IDLE-BAIT.md`, `SIDETONE.md`, `PHILOSOPHY.md`, `RFP-GALLERY.md`,
`RFP-PAYPHONE.md`, `cad/CAD-BACKLOG.md`). New scripts, all code-shaped and
therefore fair game for an unattended nightly pass to extend/harden
(but NOT to mark "verified" — none of this has touched real audio
hardware yet, see the acceptance-bar note in `.claude/commands/
nightly-batch.md`):
- `bin/crt-earcon.sh`, `bin/crt-report.sh`, `bin/crt-idle-teaser.sh` — new,
  untested by ear/against live traffic. Safe unattended work: dry-run them
  (syntax, obvious logic bugs), NOT claiming they sound good or that the
  teaser cadence feels right — those need a human on the handset.
- `bin/crt-announce.sh` — bugfixed (stale TV device string). Low-risk to
  re-verify against `crt-tts.py`'s current `DEXTER_DEVICES` if that file
  changes again.
- Two open questions logged in `.claude/QUESTIONS.md` need Chris, not a
  guess: handset audio guest-vs-host routing (blocks sidetone), and
  idle-bait quiet hours.

## Parking lot: deep end-state vision — see PARKING-LOT.md
RF power-on-TV-when-handset-lifts, HDMI-to-RF multi-channel personas, hidden
transcription (blinking cursor only), predictive-typing-then-overwrite
aesthetic, two core jobs (morning reports + media playback), start on
dexter/Ryzen natively while the Compute Stick waits on a DAC. Not being
built yet — captured so the direction survives.

## Compute stick (still blocked, physical)
No progress possible remotely -- flashing/booting the actual Intel Compute
Stick STK1AW32SC needs hands on the physical device. The Ubuntu Server ISO
noted as "downloaded on mandark" in a prior session's scratchpad could not be
found this session (scratchpad from that session no longer exists) -- if
still needed, redownload before the next hands-on session.

## Autonomous overnight batch (enabled 2026-07-19)

crt is now a git repo pushed to a LOCAL bare remote (`~/git-remotes/crt.git`),
and registered with the scheduler's Tier 2 batch (`schedule/crt.conf`), 3
passes/night (01:45/03:45/05:45), 30-day auto-sunset. Each run reads this file
+ `AUDIO-DEBUG.md` and advances the code-shaped backlog (audio approaches, STT
watchdog/single-reader, USB firmware, video wrapper), branching around anything
physical. Reports land in `~/reports/crt/`. A GitHub mirror is optional later
(deploy key `~/.ssh/crt_deploy_key` is ready; swap `REPO_URL` in the conf).
