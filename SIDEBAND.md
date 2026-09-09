# Sideband: an ambient presence channel

A third, distinct audio concept alongside `SIDETONE.md` (hearing your own
voice) and `crt-earcon.sh` (one-shot discrete chimes for discrete events):
a **continuous, very-quiet ambient texture** in the earpiece that signals
the console's *ongoing state* — idle, listening, thinking, speaking —
peripherally, the way an old modem's hum or a computer's fan tells you
something without ever needing conscious attention. This is "calm
technology" applied to sound: information that lives at the edge of
awareness, not a channel competing for it.

## Why this is a fourth thing, not a variant of the other three
- **Sidetone** answers "is my voice reaching the mic" — it's *your* voice,
  fed back.
- **Earcons** answer "something just happened" — discrete, one-shot,
  event-triggered.
- **Sideband** answers "what is the machine doing *right now*" —
  continuous, state-triggered, present even when nothing has "happened."
None of the other three cover that last question, and per
`STT-MECHANISM.md`'s framing of this as a noisy room, "is it even
listening right now" is a real, recurring uncertainty worth a dedicated,
always-available answer — cheaper than asking out loud every time.

## Respecting restraint (PHILOSOPHY.md #3)
The obvious failure mode is this becoming background noise nobody asked
for. Two guards, both non-negotiable:
1. **Idle state is near-silent — arguably true silence.** The "as close to
   nothing as possible" principle applies here just as much as to the
   screen. There is no ambient texture for "nothing is happening"; silence
   *is* that signal.
2. **Always ducks for anything louder.** The moment an earcon or TTS wants
   the same device, sideband mutes immediately, no fade, no negotiation —
   it is never allowed to compete with, mask, or be confused for an
   intentional sound.

## The four states
| State | Texture | Volume | Rationale |
|---|---|---|---|
| `idle` | none | 0 (silent) | resting state, matches CRT screen's own restraint |
| `listening` | a very faint, steady soft-noise bed | lowest audible | "the line is live" — a synthetic stand-in for what hardware sidetone would give for free, useful regardless of how `SIDETONE.md`'s open guest-vs-host question resolves |
| `thinking` | the same bed, gently amplitude-pulsed (a slow "breathing" rhythm) | slightly above listening | "the gears are turning" — old-computer-processing-sound energy, distinct from listening by *rhythm*, not just volume, so it's tellable apart without conscious effort |
| `speaking` | none (fully ducked) | 0 | TTS/earcons own the device outright while active |

## Shipped 2026-07-20 (offline; the tone loop itself is unheard)
`bin/crt-sideband.sh` runs the loop, `bin/crt-sideband-set.sh
<state>` is the transition helper, `crt-stt-solo.py` is the sole writer
of `listening`/`thinking` (opt-in, off by default), and `crt-tts.py` /
`crt-earcon.sh` duck it unconditionally with a `finally`/`trap`-guaranteed
unmute. Each script's own header comment covers its own piece now, not
duplicated here. Covered by `tests/test_sideband.sh` (the pure
state-to-tone-spec mapping), `tests/test_sideband_wiring.py` (stt-solo
gate + tts duck), and `tests/test_earcon_sideband_duck.sh` (real sox
render).

## Not done this session
- The tone textures themselves (a noise bed + a pulse) are still a first
  guess, completely unheard — none of the wiring above changes that.
  `EXPRESSIVE-TONE.md`'s register taxonomy could eventually extend to
  this channel too (a "clipped/urgent" sideband texture during a real
  blocker?) — not attempted this pass, listed as a future thread rather
  than guessed at blind.
