# crt — current state & handoff

Voice-driven secretary console: a landline handset + CRT TV as the human
interface. This doc is the pick-up-where-we-left-off summary — read this
first, then follow the pointers below for depth on any one piece.

**Read next, depending on what you're doing:**
- `README.md` — the how-and-why of each original piece, incl. detailed audio
  troubleshooting.
- `gh issue list -R hf7y/crt` — current backlog/status; the file backlog is retired.
- `SECRETARY.md` — the actual product vision (phone secretary, not a raw STT
  terminal) and what's built vs. still design-only.
- `AUDIO-DEBUG.md` — mic capture staleness debugging (5 parallel approaches).
- `vault:crt/AUDIO-ROUTING.md` — TV vs. phone-earpiece audio output separation.
- `vault:crt/PARKING-LOT.md` — the deep end-state vision (RF power-on, hidden
  transcription, predictive-text feel, morning-reports + media-playback as
  the two core jobs). Not built, captured so it isn't lost.
- `SCANNER.md` — USB 1D barcode scanner, forwarded into the console's tmux
  pane. Read this before `BOOK-GAME.md`'s scanner-passthrough note.
- `BOOK-GAME.md` — barcode-scan book trivia game, standalone build, doubles
  as structured STT training-data collection and a personal library
  registry.
- `POTATO.md` — the live console hardware (a Raspberry Pi).

## Current topology (2026-08-29)

`potato` (a Raspberry Pi) is the live console — real ALSA hardware, no VM.
`dexter` now hosts the **Zaxon** relay (`provision/dexter/zaxon/`),
reachable over tailscale — not the Windows+VirtualBox `crt-vm` host this
file used to describe. That earlier topology (2026-07-19 through
2026-07-21: dexter as a Windows 11 + VirtualBox host, mandark as the
manual deploy hop, the tmux window layout that ran on `crt-vm`) is archived
byte-for-byte at `vault:crt/HANDOFF-20260829.md` for anyone digging into
that era's history — none of it describes what's running today.

Current state, blockers, and access gaps live in
`gh issue list -R hf7y/crt`, not in this file.
