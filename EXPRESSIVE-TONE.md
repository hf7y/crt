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
Register is two cheaply-combined axes: a base tone (bait/question/success/
ack/oops/curious/content) for *what kind of thing this is*, then
**`CRT_EARCON_FADE_SCALE`** scales that tone's fade for *how urgent it
feels right now* — rather than hand-authoring a distinct sound per
register. `curious`/`content` are a genuinely new pitch-contour pair, not
just fade variants of existing tones. The scale values, per-tone contour
choices, and the rationale for each (why `curious` isn't just a slower
`bait`) now live in `bin/crt-earcon.sh`'s own header and case-arm comments,
not duplicated here.

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
  **DONE (2026-07-20)** — `bin/crt-earcon.sh`'s `sweep()` glissandos, see
  its own comments. Still unheard by a human; synth-render is the only
  offline verification.
- No color/brightness dimension yet, despite `CLAUDE.md` explicitly
  granting ANSI control of the screen — a natural extension (register
  also picks a color, not just line length) that this pass didn't reach.
  Worth its own follow-up rather than bolting on hastily.
- ~~No TTS prosody control~~ **DONE (2026-07-20)** — `bin/crt-tts.py`'s
  `--mood`/`MOOD_PRESETS` (its own comment points back at this file's
  register table) plus explicit `--pitch-semitones`/`--rate-mult`/
  `--volume-mult` overrides; no flags = byte-identical to the old
  behavior. `tests/test_tts_prosody.py` covers it; never heard by ear —
  no TTS backend installed in this sandbox.

## Status
Design + a first mechanism (`CRT_EARCON_FADE_SCALE`, `curious`/`content`
tones) built this session. Untested by ear, like everything audio in this
project right now — the whole register taxonomy is a hypothesis about
what will actually *feel* right, not a settled fact, and needs a human ear
to validate or revise once the VM is reachable again.
