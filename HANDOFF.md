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

### potato's SSH host keys (recorded 2026-09-18)

    ED25519  SHA256:mrixOpBAg+5Dw9RDosa2Y/5TRwrlCuS3i6GB0NB3JLs
    ECDSA    SHA256:w+XhU6NJJsHQsUQXw613GDUtECBnzzFn30ctj6GWLVI
    RSA      SHA256:gJ19h5hZm63NsgvRhKTawGF1OfqNsXvEsDxKiUgPqqM

Here because they were **nowhere in this tree**, and that is what stalled
crt#342: monkey's `ssh potato` now resolves and connects over tailscale, and
stops at host-key verification with nothing to check the fingerprint against.
A first connection with no recorded fingerprint is trust-on-first-use against
whoever answers, which is not a thing to do blind on a box that holds a
deploy key.

Read off `/etc/ssh/ssh_host_*_key.pub` on potato itself over an already
authenticated session — not scanned from the network, which would prove
nothing a spoofer could not also arrange. The ED25519 line independently
matches mandark's own `known_hosts` entry from an earlier verified
connection, and matches the fingerprint crt#342 saw from monkey.

Reaching potato at all: prefer `ssh -i ~/.ssh/vkv_deploy_key
vkv@100.81.177.122` over the `Host potato` alias, which on mandark still
points at the pre-move LAN address and gets `No route to host` (see
`CLAUDE.md`, and crt#323 for the move itself).

Current state, blockers, and access gaps live in
`gh issue list -R hf7y/crt`, not in this file.
