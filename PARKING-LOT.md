# Parking lot: deep crt end-state ideas (2026-07-19)

Not being implemented now — captured so the direction isn't lost. Revisit
once the core secretary loop (SECRETARY.md) and a working transcription
backend are solid.

## Physical/RF concept
- Handset rests on a hook; **lifting it sends IR to power the TV on**
  (like an old-school remote-control power trigger), rather than the TV
  being always-on. Micro computer hidden inside a re-purposed shell
  (candidate: gut an old phone/answering machine chassis).
  **Corrected 2026-07-20** (was "RF" in the original note — an error,
  per direct correction: "IR transmitter should work"): TV power-on is
  the same IR mechanism as the channel-change idea below, not a separate
  RF trigger — one IR blaster likely covers both jobs. See
  `BLOCKERS.md`'s crt deep-vision section for the sourced part
  (`cad/ir_blaster_mount.scad` already has a placeholder mount).
- **HDMI-to-RF modulation** could carry up to 4 channels — different
  "streams"/personas or modes could live on different TV channels.
  **Update 2026-07-20**: the modulator itself is already owned (supports
  this multi-channel/daisy-chain feature) — the remaining blocker is
  housing/mounting/wiring integration, not sourcing. See
  `cad/CAD-BACKLOG.md`.
- Each channel/persona could reinforce its identity by **beaming IR remote
  codes** (channel-change, power) as part of its own behavior — e.g.
  switching mode = actually changing the TV's channel via IR blaster.

## Interface philosophy
- On-screen: as close to nothing as possible. A **blinking cursor**, not a
  transcript. **Hide the STT transcription entirely once past debugging** —
  today's `crt-stt-speakback.sh`/debug view is explicitly a *debugging*
  tool, not the end state. Transcription errors get silently absorbed by
  the response being elegant/charitable about intent, never shown raw.
- End result reads as a **chatbot that runs as locally as possible**, with
  occasional callouts to Claude Code / a hosted service only when needed
  (e.g. genuinely open-ended requests) — most turns should be answerable
  locally and fast.
- **Aesthetic: the bot starts typing/responding first** using a cheap local
  autocomplete/predictive-response guess (instant, no perceptible latency),
  then **overwrites with the real answer** once a slower callout (Claude
  Code or similar) returns — gives an immediate "it's alive" feel while
  hiding real latency. (Conceptually similar to speculative decoding /
  optimistic UI patterns — cheap local model guesses, authoritative source
  corrects.)

## Two primary jobs (the actual product surface)
1. **Morning reports** — spoken/printed summary on request or schedule.
2. **Play media** — voice-driven local media playback (VLC/ffmpeg-class
   tooling), i.e. "play the thing", "next", "pause" via handset voice.

Everything else (MIDI knobs, TV announcements, pager, etc.) is in service
of these two jobs and the general secretary loop, not separate features.

## Interface hardware priority
**Handset + hookswitch are primary.** Not CRT-as-display, not MIDI knobs —
those are debug/nice-to-have. The hookswitch (off-hook = start listening,
on-hook = stop/power down) is the fundamental interaction model, closer to
an actual telephone than a computer terminal.

## Multiple phone installations (2026-07-19, gallery/art concept)
Two separate installation ideas, distinct from the personal-secretary crt.
Both got real direction 2026-07-20 — see `RFP-GALLERY.md` and
`RFP-PAYPHONE.md` for the full updated briefs:
1. **Distributed answering machines for a gallery** — visitors can leave
   messages or receive them; phones that physically ring when there's
   something waiting. Multiple units, presumably networked to a shared
   backend (or independent per-phone). **Direction given 2026-07-20**:
   leaning toward either autonomous networked Pis (one per unit, can
   interact with each other) or a POTS-wiring hack — see `RFP-GALLERY.md`
   for the possibilities writeup comparing them.
2. **A payphone people actually pay quarters into** — coin mechanism routes
   to a TTS/AI backend that "does something" (answers questions, has a
   conversation). Stretch idea: a token economy — sometimes it gives more
   tokens back than were inserted, turning it into more of a game/gamble
   than a straightforward vending transaction. **Resolved 2026-07-20**:
   quarters used as the test-phase token, real coin mechanism throughout
   (not a separate token-only build), never deployed for real money — see
   `RFP-PAYPHONE.md`, the earlier legal-check blocker no longer applies
   under this framing.

## Video cast to CRT (2026-07-20, scoped)
Later goal, now has real shape — see `VIDEO-CAST.md`.

## Deployment sequencing
- **Start on the Minisforum Ryzen (dexter)** as the primary/first working
  target — full native speed, no VM/compute-stick constraints, matches the
  faster-whisper-network-service direction already in progress.
- **Intel Compute Stick is next**, once a DAC arrives (needed since the
  stick has no analog audio in — see README's bare-metal notes). Until the
  DAC shows up, the stick work is blocked/waiting, not actively pursued.

## Scheduler integration (2026-07-19, user)
Look into hooking crt itself into the scheduler ecosystem beyond just being
a registered nightly-batch participant (already done, see
`schedule/crt.conf` in the scheduler repo) — e.g. the phone/secretary
interface (SECRETARY.md) as an actual delivery surface for scheduler
reports/questions (spoken/printed morning reports, ring for an open
QUESTIONS.md item), not just crt's own code getting nightly attention.
Needs a concrete design pass, not scoped yet.

## Code consolidation across dexter / the VM / mandark (2026-07-19, user)
Project code is currently scattered across multiple machines (dexter's
native Ryzen work e.g. `bin/dexter-whisper-server.py`, the Windows VM guest
side, and mandark as the batch host). Consolidate into one place (this repo
is presumably the target, since it's what's git-managed and scheduler-
registered) so there's a single source of truth instead of code living
wherever it happened to be written. Needs an inventory pass first: what
exists on each machine, what's already mirrored here vs. only local.

## MIDI controller pass-through (parked 2026-07-20)
Goal: pass the Arturia MiniLab through to `crt-vm` so its pads/knobs can
drive the console (control-file writes, same channel as other HUD input —
see `crt-midi-knobs.py`). **Status when parked**: root cause of the original
failure was found and fixed (Windows had the MiniLab's MIDI interface
disabled, `CM_PROB_DISABLED` in Device Manager — fixed via
`Enable-PnpDevice`), but `VBoxManage usbattach` still fails ("busy with a
previous request") even after that fix and a full VM power-cycle
(`controlvm poweroff` + `startvm`, done live 2026-07-20 for an unrelated
audio issue — didn't clear this either). Points to a stuck VBoxUSB/VBoxSVC
host-proxy state, independent of the PnP fix. **Next step, whenever this is
picked back up**: kill/restart the `VBoxSVC.exe` process tree on dexter (a
process-kill action that needs a human's direct OK — the live VM depends on
it, don't do this mid-session without checking first) and retry
`usbattach`, or fall back to a full dexter reboot if VBoxSVC restart alone
doesn't clear it.

**Direction** (from `BLOCKERS.md`, 2026-07-20): develop this on the
dexter/Windows side for now, but with the explicit long-term intent it
merges back into the bare-metal Linux distro eventually (see README's
"Bare-metal deployment" / "Porting to native Windows later" sections) — so
design/wiring choices made here should stay portable, not lean on anything
Windows-only that would need re-solving on the eventual Linux target.

Deprioritized twice now (2026-07-19 "abandon midi, pick it up later"; parked
again 2026-07-20 to keep this session's live-access time on blockers that
actually cleared) — not on the critical path for the core voice console.
