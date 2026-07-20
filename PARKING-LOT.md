# Parking lot: deep crt end-state ideas (2026-07-19)

Not being implemented now — captured so the direction isn't lost. Revisit
once the core secretary loop (SECRETARY.md) and a working transcription
backend are solid.

## Physical/RF concept
- Handset rests on a hook; **lifting it sends RF to power the TV on**
  (like an old-school remote-control power trigger), rather than the TV
  being always-on. Micro computer hidden inside a re-purposed shell
  (candidate: gut an old phone/answering machine chassis).
- **HDMI-to-RF modulation** could carry up to 4 channels — different
  "streams"/personas or modes could live on different TV channels.
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
Two separate installation ideas, distinct from the personal-secretary crt:
1. **Distributed answering machines for a gallery** — visitors can leave
   messages or receive them; phones that physically ring when there's
   something waiting. Multiple units, presumably networked to a shared
   backend (or independent per-phone).
2. **A payphone people actually pay quarters into** — coin mechanism routes
   to a TTS/AI backend that "does something" (answers questions, has a
   conversation). Stretch idea: a token economy — sometimes it gives more
   tokens back than were inserted, turning it into more of a game/gamble
   than a straightforward vending transaction.

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
