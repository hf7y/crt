# crt as a phone secretary, not a raw Claude Code terminal

**Reframing (2026-07-19):** the ultimate goal isn't "STT typed into Claude
Code." It's a **secretary-like service** reached via the handset — Claude Code
is the backend brain, but the phone interaction should feel like talking to an
assistant, not dictating into a terminal. This file tracks that direction so
it isn't lost; not fully implemented yet, most of it is design + a couple of
supporting scripts (TTS, pager) that will be reused by whatever wrapper
eventually replaces the raw "type into Claude's pane" model.

## Output channels, by length/urgency
- **Printer (Phomemo M02, `bin/catprint`)** — the channel for anything long:
  job/report status, logs, anything you'd scroll through. Long text does NOT
  belong on the CRT.
- **CRT** — short status + interactivity only. If something longer genuinely
  needs to show there, it scrolls **slowly** rather than dumping — see
  `bin/crt-pager.py` (line-by-line auto-scroll, pause/resume/jump via the
  shared control file, jog-able once a MIDI knob is wired to it).
- **TTS through the phone earpiece** (`bin/crt-tts.py`, calibrated via
  `bin/crt-tts-calibrate.py`) — short spoken confirmations for the person on
  the handset. This is the "secretary" voice.
- **TTS through the TV** (`bin/crt-announce.sh`, rate-limited to 1/15min) —
  for getting **Chris's** attention when he's in the room but not on the
  phone. He can only respond by talking into the handset (no clicking/typing).
  See `AUDIO-ROUTING.md` for why this is likely a host (Windows), not guest
  (VM), problem, and the current state of that bridge (not yet built).

## What a "secretary" interaction should feel like (not yet built)
Rather than every utterance being typed verbatim into Claude's terminal input
(today's model, still the working baseline), a secretary wrapper would:
1. Listen for a request ("what's my nightly build status", "tell Chris the
   report's ready", "read me the last thing that failed").
2. Hand it to Claude Code as a scoped, structured ask — not a raw keystroke
   feed — and get back a response.
3. **Speak** a short answer through the earpiece (crt-tts.py), and/or print a
   full report to the Phomemo, and/or scroll a longer answer on the CRT
   (crt-pager.py) if it must be read there.
4. Never assume the caller can read a screen — voice in, voice/print out,
   CRT only for short status glances.

## Current implementation status
- TTS engine + calibration: written, not yet audited by ear (`bin/crt-tts.py`,
  `bin/crt-tts-calibrate.py`). Deployed + smoke-tested (exit 0, no errors) on
  crt-vm 2026-07-19 via `espeak-ng`.
- Speak-back debug loop (`bin/crt-stt-speakback.sh`): runs the STT engine in
  **debug mode (stdout only, NOT wired to Claude)** and speaks back
  "heard: ..." for each transcription — lets a person on the handset debug
  the mic/STT purely by ear. Running live on crt-vm's `stt` tmux window as of
  2026-07-19 14:40 (replaced the old stt-feed.sh+crt-levels.sh pipeline for
  this debug session — restore with `crt-console.sh` for the normal
  Claude-wired flow).
- Pager (`bin/crt-pager.py`): written, syntax-tested with synthetic text
  (wraps to 40 cols, scrolls, footer shows page%/END). Not yet wired to any
  real Claude output or a MIDI knob.
- The actual "secretary wrapper" (steps 1-4 above) is **design only** — no
  code yet. Next concrete step: a thin layer in front of `tmux send-keys`
  that (a) only speaks Claude's final answer (not the whole scrollback), (b)
  decides printer vs CRT vs TTS per response length, (c) keeps the existing
  raw-STT-to-Claude path as a fallback/debug mode.
