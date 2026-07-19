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
