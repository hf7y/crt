# crt — current state & handoff

Voice-driven Claude Code console: a landline handset + CRT TV as a speech
front-end, running in a Debian VM on a Windows mini-PC. This doc is the
pick-up-where-we-left-off summary. See `README.md` for the how-and-why of each
piece, including a detailed **Audio capture troubleshooting** section.

## Where it runs

- **`dexter`** — Windows 11 Pro mini-PC (Minisforum/Ryzen). Host.
  - SSH: `ssh dexter.local` (key auth; drops into PowerShell).
  - VirtualBox 7.2.12 + Extension Pack installed. `VBoxManage` at
    `C:\Program Files\Oracle\VirtualBox\VBoxManage.exe` (call via `& "..."`).
- **`crt-vm`** — Debian 13 guest on dexter. The console itself.
  - SSH: `ssh -p 2222 zach@dexter.local` (NAT port-forward 2222→22, key auth).
  - Password `kw0kWXESrKQpNvuKXiU8`; passwordless sudo enabled.
  - To see its screen: at dexter's KVM, open **VirtualBox Manager** and
    double-click `crt-vm` (GUI mode). Do NOT use "Show" on a headless VM (hangs),
    and do NOT `startvm --type gui` over SSH (no window appears).
- **`mandark`** — Dell XPS 13 (this Linux laptop). Dev box; where the repo and
  the deferred-feature archive live. Also has whisper.cpp built for local tests.

## What works now (core STT)

Voice → whisper → Claude Code, end to end, through the handset. The autoboot
chain (power on → tty1 autologin → `bin/crt-console.sh`) comes up unattended
into: full-screen `claude`, a hidden `stt` window running `bin/stt-feed.sh`, and
a 2-row **live mic level meter** strip at the bottom.

Calibration that made it work (all persistent):
- **Windows "Microphone Boost" +20/+30 dB** on dexter — THE key fix. Without it
  the handset signal was ~1.4% of full scale and whisper only hallucinated.
- Guest ALSA `Input Source` = **Line** (VirtualBox routes the host mic to the
  HDA codec's Line input, not Mic). stt-feed re-asserts this on every start.
- User in the **`audio`** group (else `/dev/snd` is unreachable over SSH).
- `CRT_VAD_THRESHOLD=1.5` (speech ~16% peak, AC floor ~4% peak with boost on).
- Per-utterance normalize + whisper-hallucination filter + single-word voice
  control keys ("enter"/"yes"/"no"/"up"/"down").
- `claude` launches with `--permission-mode bypassPermissions` (zero prompts).
- Console tuning knobs live in `~/.bash_profile` (CRT_VAD_THRESHOLD,
  CRT_AUDIO_DEV=crtmic, CRT_CLAUDE_ARGS) and `/etc/default/grub`
  (`video=Virtual-1:640x480` — CRT overscan/bezel knob).

## Shared audio capture (why dsnoop)

Raw ALSA capture is single-consumer, but the console needs stt-feed AND the
level meter reading the mic at once. `/etc/asound.conf` defines a `dsnoop`
device **`crtmic`**; both read it via `arecord`. Keeping one stream continuously
open (the meter) also keeps VirtualBox's emulated capture **warm** — the
suspected cure for the intermittent "stops detecting" (stt-feed's per-utterance
open/close was letting the capture go stale). Gotchas already paid for: stale
stuck `arecord` procs block new dsnoop readers; `arecord | python3 -` steals
stdin from the audio (meter python lives in its own file, `bin/crt-meter.py`).

## Open / in-progress

- **Standalone STT view** (`bin/crt-stt.sh`) — JUST ADDED, lightly tested.
  A focused screen (transcription log + meter, no claude) via
  `CRT_STT_SINK=stdout` in stt-feed. Built because transcriptions were hard to
  see inside claude. **Verify it runs** and shows timestamped phrases.
- **Intermittent signal drop** — watch the meter; if it goes flat mid-speech,
  add a watchdog that re-opens capture. The warm-stream fix may already cover it.
- **MIDI controller** — Arturia MiniLab mkII (VID 1c75 PID 0289). USB 2.0
  (EHCI) passthrough is enabled and VirtualBox "Captured" it, but it was **not
  enumerating** in guest ALSA (`amidi -l` empty) last we looked. Intended use:
  pads → Enter/Esc/arrows (unambiguous prompt control), knobs → scroll.
- Everything else is parked in the deferred-feature archive (see
  `~/Documents/Project Archive/scheduler/`).

## Deferred (archived)

Moved out of focus to `~/Documents/Project Archive/scheduler/`: the physical
hookswitch build, OctoPrint on a spare Pi, a Benchy calibration print, the USB
phone-interface module (for the bare-metal Intel Compute Stick target), and a
stretch video-call wrapper. The Ubuntu Server ISO (for the compute stick's
32-bit-UEFI quirk) and the official 3DBenchy STL are downloaded on `mandark`
under the session scratchpad.
