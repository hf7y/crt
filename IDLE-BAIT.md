# Idle bait: getting Chris to pick up the phone

**Design goal (Chris, 2026-07-19, mid-session):** debugging/status surfacing
should always read as **cute idle bait that tricks Chris into helping** —
never as an annoying nag that makes him turn the TV off. The moment this
starts feeling like a notification badge, it has failed. This doc is the
workflow design; nothing here is built yet except the two pieces marked
DONE below.

## The loop

```
job runs (nightly batch, or this session) --> writes a report/question
        |
        v
CRT idle state shows a small, curious cue (never a wall of text)
        |
   (Chris notices, is charmed/curious, picks up the handset)
        |
        v
off-hook --> STT active --> he asks "what's up" / anything
        |
        v
secretary pulls reports+questions, answers by VOICE first, offers print
        |
        v
if he answers a pending judgment call, it's written back (QUESTIONS.md
`> ` convention) so the next nightly batch treats it as authoritative
```

The two ends of this loop already exist independently and just need
connecting:
- **Report/question side**: the scheduler's existing convention
  (`~/reports/<project>/LATEST.md`, `.claude/QUESTIONS.md`,
  `bin/morning-report.sh` in `Project Archive/scheduler`) — crt should
  **reuse this verbatim**, not invent its own format. Every other project
  (chezz, wtul, vkv-inventory, home-assistant) already writes reports this
  shape; `morning-report.sh` already aggregates them. crt's Tier 2 nightly
  batch is registered (`schedule/crt.conf`) but not yet actually producing
  `~/reports/crt/LATEST.md` — see "What's missing" below.
- **Pickup side**: `bin/crt-ring.sh` (tone + voice-in-the-gap pickup
  detection) and `bin/crt-tts.py --device handset` already work.

## Why "bait," not "alert"

An alert says *something is wrong, deal with it*. Bait says *something
interesting happened, come look*. Same underlying event (a job hit a
blocker), completely different framing — and framing is the whole game
here, because the failure mode isn't "he doesn't see it," it's "he mutes
the TV." Concretely:

- Never phrase a cue as a demand ("3 blockers need your attention").
  Phrase it as a hook ("the chess floor thing turned out to be a 9-wide
  row — weirdly satisfying, ask me about it").
- A blocker that's purely informational (needs no human input, just FYI)
  doesn't get audio at all — it's bait for *curiosity*, not obligation. It
  sits on screen quietly. Genuine judgment calls (QUESTIONS.md entries)
  are the ones worth a chime, because those are the ones where his 30
  seconds on the handset actually unblocks tomorrow night's run.
- One cue per new distinct item, ever. No re-announcing an unresolved
  question on a timer — that's the nag pattern. It sits there, patient,
  until he deals with it or a newer/better item replaces it as the bait.

## On-screen idle state (CRT)

Per `PARKING-LOT.md`'s existing interface philosophy ("as close to nothing
as possible... a blinking cursor, not a transcript"), the idle screen stays
minimal. Proposal, layered on top of that blinking cursor:

- Default: just the cursor.
- When a new report/question lands: the cursor (or a small glyph next to
  it) changes color/blinks a different pattern, plus **one line** of
  in-character teaser text (reusing `crt-monologue.sh`'s first-person
  narration style — it already tails a log and prints word-wrapped
  first-person lines, so this is presentation, not new plumbing). E.g.:
  `"i found something in the chess floor. wanna hear?"`
- Never more than one teaser line resident at a time — newest item wins,
  older undealt-with items are still in the underlying report/questions
  file, just not fighting for screen space.

## Audio cue (the actual "bait" sound)

This is where "never annoying" has to be a hard rule, not a vibe:

- **One shared rate limit across all idle-bait audio**, not per-source.
  `crt-announce.sh` already has a 15-minute lockfile — reuse that same
  lockfile for the idle-bait chime too (see `crt-earcon.sh` design below)
  so a report chime and a TV announcement can't stack into a barrage.
- **One chime per distinct new item**, never a repeat for something
  already surfaced and still unanswered. (Needs a small "have I already
  chimed for this" marker — cheapest implementation: hash the report/
  question's first line, store seen-hashes in `~/.crt/idle-bait.seen`.)
- **Idle timeout, not clock-based quiet hours** (resolved 2026-07-19, per
  Chris: "like a screensaver... a combination of low handset volume and
  other markers going idle"). The whole mechanism — teaser line AND
  chime, not just audio — only activates once the room's been quiet for a
  while, same idea as a screensaver only appearing after inactivity, not
  a fixed hour-of-day window. Implemented in `crt-idle-teaser.sh`:
  `is_idle()` checks the newest mtime across `~/.crt/stt.log` (someone
  spoke) and `~/.crt/sideband.state` (a state transition happened,
  `SIDEBAND.md`) against a timeout (`CRT_IDLE_TIMEOUT_SECS`, default 20
  minutes — a first guess, needs tuning once live). `~/.crt/mic-level` is
  reserved as a marker path for a future lower-bar "someone's near the
  phone" signal (a raw peak ping from `crt-stt-solo.py`, below the VAD
  utterance threshold) — nothing produces it yet, harmless to list since a
  missing marker just doesn't count as recent.
- **Backoff on no-pickup**: if `crt-ring.sh` times out unanswered, do not
  retry on any fixed schedule — that's the exact "he turns the TV off"
  failure mode. Let the next *genuinely new* item be the next bait; don't
  re-ring for the same one.
- The chime itself should sound curious/playful, not alarm-like — see
  `crt-earcon.sh` (below) for the actual tone design; this is also where
  "expressive beeps" (Chris's other ask) lives.

## What's missing to make this real (in order)

1. ~~`~/reports/crt/LATEST.md` doesn't exist yet~~ **DONE (2026-07-19)**:
   `bin/crt-report.sh` writes it in the scheduler's exact shape
   (`--blocker`/`--question`/plain note), so idle-bait has content even
   before crt's Tier 2 nightly batch actually runs (still just registered,
   see `HANDOFF.md`).
2. The secretary wrapper (`SECRETARY.md` steps 1-4) is still design-only —
   it's the thing that actually answers "what's up" by voice once he picks
   up. Idle-bait is the *lure*; the secretary wrapper is the *payoff*. This
   doc doesn't change that dependency, just names it.
3. ~~`crt-earcon.sh` — not built yet~~ **DONE (2026-07-19)**: `bin/crt-earcon.sh`
   (bait/question/success/ack/oops tones), untested by ear.
4. ~~idle-screen teaser line~~ **DONE (2026-07-19)**: `bin/crt-idle-teaser.sh`
   is a separate watcher (deliberately not baked into `crt-monologue.sh` —
   see `PHILOSOPHY.md`'s open thread on narration vs. restraint) that polls
   `~/reports/crt/LATEST.md` + `QUESTIONS.md`, dedupes by line hash
   (`~/.crt/idle-bait.seen`), and emits one `crt-think.sh` teaser + (for
   real judgment calls only) one `crt-earcon.sh` chime per new item,
   sharing `crt-announce.sh`'s rate-limit lock so nothing can stack.
   Not yet run against live traffic — needs a VM session to actually watch.

## Explicitly not doing

- No polling-driven repeated reminders. Ever. This is the one rule the
  whole design bends around.
- No stacking multiple pending items into one alarming "N things need you"
  summary — that's exactly the notification-badge feeling this is trying
  to avoid. One teaser at a time.
