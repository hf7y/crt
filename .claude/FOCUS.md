# crt — focus & backlog

**Current focus: the core STT pipeline.** Everything below the line is
deliberately parked so interactive sessions stay on getting voice→text→Claude
reliable. See `../HANDOFF.md` for full state and access.

## Now (core STT)

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
- The standalone STT view (`bin/crt-stt.sh`) — verify it runs and is useful for
  watching/tuning transcription, decoupled from Claude.
- Ongoing calibration: `CRT_VAD_THRESHOLD`, Windows mic boost, normalization.

## Deferred (not in current focus — do not pull these into an STT session)

These are tracked here so they're not lost. Most are **physical/hardware** and
cannot be done by an autonomous agent. The scheduler's overnight batch (now
enabled — see below) is scoped to the CODE-shaped items only and told to branch
around anything needing hands on hardware or a live VM.

1. **MIDI controller** (Arturia MiniLab mkII, USB 1c75:0289). USB2/EHCI
   passthrough enabled; device was "Captured" by VBox but not enumerating in
   guest ALSA. Goal: pads → Enter/Esc/arrows for prompt control, knobs → scroll.
2. **Physical hookswitch** — handset on-hook/off-hook detection; pads/reed
   switch → mute + pause STT + (stretch) TV power. See `cad/` and README.
3. **OctoPrint** on a spare Raspberry Pi (OctoPi SD already flashed on mandark).
4. **Benchy calibration print** once the Ender 3 SD path is verified (3DBenchy
   STL downloaded on mandark).
5. **USB phone-interface module** — for the bare-metal Intel Compute Stick
   target (no 1/8" jack; audio must go over USB). Composite USB device:
   audio + HID for hookswitch. Ubuntu Server ISO downloaded (32-bit-UEFI quirk).
6. **Stretch: video-call wrapper** (Zoom/WhatsApp) over the handset/CRT.

## Autonomous overnight batch (enabled 2026-07-19)

crt is now a git repo pushed to a LOCAL bare remote (`~/git-remotes/crt.git`),
and registered with the scheduler's Tier 2 batch (`schedule/crt.conf`), 3
passes/night (01:45/03:45/05:45), 30-day auto-sunset. Each run reads this file
+ `AUDIO-DEBUG.md` and advances the code-shaped backlog (audio approaches, STT
watchdog/single-reader, USB firmware, video wrapper), branching around anything
physical. Reports land in `~/reports/crt/`. A GitHub mirror is optional later
(deploy key `~/.ssh/crt_deploy_key` is ready; swap `REPO_URL` in the conf).
