# Philosophy

`PARKING-LOT.md` captured the first pass at this ("as close to nothing as
possible," blinking cursor, hidden transcription). This doc names the
underlying principles explicitly and pushes them further — the "why" behind
the parking lot, and behind `IDLE-BAIT.md`/`SIDETONE.md`. Living document;
extend it rather than replacing sections as the project teaches us more.

## 1. Answer first, be right later
The predictive-typing-then-overwrite idea in `PARKING-LOT.md` (cheap local
guess appears instantly, gets overwritten by the real answer once Claude
Code returns) isn't just a latency trick — it's the same move as:
- **Earcons before words** (`crt-earcon.sh`): a beep lands in ~0ms, the
  actual spoken answer follows once it's ready. The beep is the "it's
  alive" signal; the words are the correction.
- **Sidetone** (`SIDETONE.md`): hearing yourself instantly, before any
  system has processed anything, is the most extreme version of this — the
  "response" is just physics, not computation.
- **Idle bait teasers** (`IDLE-BAIT.md`): a one-line hook now, full detail
  only once he picks up and asks.
The pattern: never make a human wait in silence for the *right* answer when
a cheap, honest, *immediate* signal is available. Silence reads as broken;
imperfect-but-instant reads as alive.

## 2. Cost-of-ignoring should be near zero
Modern notification design works by making ignoring expensive (badges,
red dots, repeat pings) — it wins attention through friction, not
interest. This project deliberately inverts that. `IDLE-BAIT.md`'s core
rule (one cue per item, no repeats, no stacking) means **the system never
punishes Chris for not noticing**. If bait doesn't land, it just... sits
there, patient, and waits for something more interesting to replace it.
This is a bet that genuine curiosity pulls harder over the long run than
urgency does, and that urgency-based design is exactly what teaches people
to tune a device out (or unplug it) — the plain failure mode this whole
project is explicitly designed around avoiding.

## 3. Restraint as trust-building, not just aesthetics
An always-listening device in a home is inherently fraught. "As close to
nothing as possible" on-screen, no visible transcript, minimal standing
footprint — this isn't a minimalist aesthetic choice first, it's a trust
argument: the less this thing visibly *asserts itself* when idle, the more
its occasional bait/announcement means something when it does show up.
A device that's quiet 99% of the time earns the right to speak the other
1%. A device that's always narrating itself earns nothing — it's wallpaper.
(Practical tension worth naming: `crt-monologue.sh`'s first-person
narration is currently *on by default* on the active screen. Worth
revisiting whether that's still "restraint" once the idle-bait teaser line
is layered on top, or whether it's competing for the same scarce attention
it's supposed to be spending carefully. Open thread, not resolved here.)

## 4. Verbs, not menus
Lifting the handset, hanging up, (eventually) an IR channel-change to
switch modes — these are bodily rituals with real friction and real
finality, not taps on a flat menu. The design privileges physical action
that means something (picking up a phone is a *decision* in a way tapping
an icon isn't) over app-like navigation. This is also why the hookswitch
is explicitly the "primary" interface hardware per `PARKING-LOT.md`, ahead
of the CRT or any knob — it's the one piece of hardware that IS a verb.

## 5. One body, several selves
The HDMI-to-RF multi-channel idea (`PARKING-LOT.md`) — different personas/
modes living on different TV "channels," each reinforcing its identity by
actually changing the channel via IR when it activates — proposes
something more specific than "modes": each channel is close to a distinct
character sharing one body, summoned the way you'd change the channel on
an old TV, not the way you'd switch tabs in an app. Worth taking
seriously as a design constraint rather than a stretch feature: if this
is real, then *interruption between personas should feel like changing
the channel*, not like closing one app and opening another — same
physical-verb principle as #4, applied to internal state instead of
on/off.

## 6. Imperfection is character, not a defect to hide
`STT-MECHANISM.md` already frames mishearing as a pipeline to understand,
not a black box to blame. Philosophically: this console is more like a
slightly-deaf old friend in a noisy room than a voice-recognition product.
The *output* stays polished (garbled input never surfaces raw per
`PARKING-LOT.md`'s "never shown raw" rule), but the *character* is allowed
to be a little hard of hearing, a little uncertain, occasionally charmed
by its own mishears (see `CLAUDE.md`'s "did you say fax or facts, asking
for research purposes" spirit). This is a deliberate contrast with the
polished-omniscient-assistant genre most voice products aim for.

## 7. Local-first, cloud as a favor asked, not a dependency
"A chatbot that runs as locally as possible, with occasional callouts to
Claude Code only when needed" (`PARKING-LOT.md`) means the device's
*presence* (beeps, sidetone, the blinking cursor, quick local guesses)
should never depend on a network round-trip. Only genuinely open-ended
reasoning should. This is both a latency argument (#1) and an
independence argument: a device that goes fully dark the moment wifi
drops has a weaker claim to being "alive" than one whose personality is
mostly load-bearing locally.

## Open threads (deliberately not resolved — pick these up later)
- Does `crt-monologue.sh`'s always-on narration conflict with principle #3
  once idle-bait is layered in? (noted above)
- If principle #5 (one body, several selves) is taken seriously, does the
  *gallery/payphone* installations (`RFP-GALLERY.md`, `RFP-PAYPHONE.md`)
  count as new "channels" of the same character, or genuinely separate
  beings? Affects whether they should ever share a backend/persona store.
- Principle #6 says imperfection is character — where's the line? A
  mishear that changes the *meaning* of an instruction (not just charm)
  is still a real failure, not a feature. Worth a concrete severity rule
  someday: cosmetic mishear vs. intent-changing mishear should be handled
  completely differently (charm the first, always confirm the second).
