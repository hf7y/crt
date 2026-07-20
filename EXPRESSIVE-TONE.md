# Expressive tone: prosody without words

A creative/technical dive into using presentation *shape* — not content —
to carry emotional register: fade-out length, pitch contour, and on-screen
line brevity, across all three output channels (earpiece, TV, CRT text).
This is human prosody's actual mechanism, ported to a machine that mostly
can't rely on words alone: **how** something is said/shown carries as much
meaning as **what**. Extends `PHILOSOPHY.md` (this is really principle #1,
"answer first, be right later," and #6, "imperfection is character," both
made literal in sound/text shape rather than content).

## Why this instead of more words
This console's screen is tiny (40x15) and its speech should stay short
(`CLAUDE.md`: "be terse... assume every line costs scarce screen space").
Under that constraint, adding *more* expressive words is the wrong lever —
there's no room. But **how long a beep fades**, **whether a tone rises or
falls**, and **how short a line is** cost zero extra screen/speech budget
and are still legible as mood. This is the cheap, always-available
expressive channel a word-constrained device actually has.

## A small register taxonomy
Not a rigid state machine — a vocabulary to draw from consistently, so the
same shape always means roughly the same thing (consistency is what makes
prosody legible at all; random variation reads as noise, not expression).

| Register | When | Fade | Pitch contour | Screen line shape |
|---|---|---|---|---|
| **clipped/urgent** | a real blocker, needs eyes soon | short (~20-30ms) | flat or sharply falling | short fragments, no flourish: "hit a snag." |
| **warm/curious** | idle-bait teaser, ordinary find | medium (~80-130ms) | gently rising | a little longer, first-person, inviting: "found something. wanna hear?" |
| **content/settled** | something finally resolved | medium-long (~150ms) | small rise-then-settle | calm, complete sentence, no hook needed |
| **wistful/quiet** | end-of-day, low-priority note, nothing needs him | long (~250ms+) | slow falling | longest, most narrative-feeling line — this is the register for pure narration/monologue, not bait |
| **public/announcement** (TV only) | `crt-announce.sh`, rate-limited | medium, but *slightly* more deliberate than earpiece equivalents | flat/measured, never playful | plainer, less first-person than earpiece — this is the "talking to the room," not "talking to you" register |

The **TV vs. earpiece split is itself a register axis**, independent of
the table above: TV is always the more public/measured version of
whatever emotional register is being expressed (per `SECRETARY.md`'s
existing TV-vs-handset channel split) — same taxonomy, turned down.

## Concrete mechanism: one dial, not five separate tone sets
Rather than hand-authoring a distinct sound for every register (doesn't
scale, gets inconsistent fast), `bin/crt-earcon.sh` now exposes
**`CRT_EARCON_FADE_SCALE`**, a single multiplier over every tone's fade
envelope. Register becomes: pick a base tone (bait/question/success/ack/
oops) for *what kind of thing this is*, then scale its fade for *how urgent
it feels right now*. Two axes, cheaply combined, rather than an
combinatorial explosion of named sounds. `CRT_EARCON_FADE_SCALE=0.3` for
clipped/urgent, `1.0` (default) for warm/curious, `2.0`+ for wistful/quiet.

Also added: **`curious`** and **`content`** earcons, a genuinely new pitch-
contour pair (not just fade variants) — `curious` is a slow gentle rise
(distinct from `bait`'s faster rise: bait says "look over here," curious
says "hm, interesting," a real register difference worth its own contour,
not just a slower version of the same one), `content` is a small settle
(rise then fall back), for when something that was pending finally
resolves — the "ahh, good" sound, which nothing in the original five-tone
set covered.

## On-screen line length as the same dial
`bin/crt-idle-teaser.sh`'s `teaser_for_line()` already varies phrasing by
kind (blocker vs. question vs. plain note) — that's the same register
table above, expressed as text shape instead of audio shape, and it was
already accidentally doing the right thing (blocker lines are the
shortest/most clipped, plain-note lines are the longest/most narrative).
This doc makes that intentional rather than incidental: **the fade-scale
dial and the line-length choice should move together** — a clipped/urgent
earcon should never be paired with a long wistful sentence, that's a
register mismatch (mouth says one thing, tone of voice says another,
exactly the kind of dissonance that reads as "off" in a real conversation).

## Explicitly not doing (yet)
- ~~No actual pitch-contour synthesis beyond simple note sequences~~
  **DONE (2026-07-20)**: `bait`/`curious`/`question` are now single
  continuous glissando sweeps (`sox`'s `f1-f2` syntax, previously only
  `oops` used it) instead of stepped notes; `content` is two joined
  sweeps (rise, then settle) instead of three discrete notes. Still
  unheard by a human — all 21 tone×fade-scale combinations synth-render
  clean, that's the only verification possible offline.
- No color/brightness dimension yet, despite `CLAUDE.md` explicitly
  granting ANSI control of the screen — a natural extension (register
  also picks a color, not just line length) that this pass didn't reach.
  Worth its own follow-up rather than bolting on hastily.
- No TTS *prosody* control (piper/espeak pitch/rate per-register) — only
  the earcons and raw text-shape were touched this pass. `crt-tts.py`
  already exposes `CRT_TTS_PITCH`/`CRT_TTS_RATE`/`CRT_TTS_VOLUME` as flat
  config, not yet per-call/per-register — a real next step once the
  taxonomy above proves out on the simpler channels first.

## Status
Design + a first mechanism (`CRT_EARCON_FADE_SCALE`, `curious`/`content`
tones) built this session. Untested by ear, like everything audio in this
project right now — the whole register taxonomy is a hypothesis about
what will actually *feel* right, not a settled fact, and needs a human ear
to validate or revise once the VM is reachable again.
