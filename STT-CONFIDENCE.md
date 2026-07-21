# STT confidence decay — spending Claude calls only where they're still needed

Origin: Zach, live voice session, 2026-07-21. Direct quote (STT-garbled but
intent clear): "at first, calls to claude for every utterance... over time
[decay]." This is the same standing goal as `CLAUDE.md`'s "Default runtime
posture" section (minimize Claude calls, local-first) applied specifically
to STT/routing confidence, not just to answer content.

## The idea

Every recognized utterance currently either types straight into Claude
(the live default) or, if `crt-secretary.py` were wired in
(`CRT_SECRETARY=1`, currently off), gets tried against a local-answer
playbook first. Either way, right now, there's no notion of the system
getting MORE confident over time about phrases it has already seen and
handled correctly — every utterance costs the same.

The proposed shape: track how many times a given utterance (or its
normalized shape) has been seen and confirmed handled correctly *without*
Claude. The probability that the SAME shape still needs a Claude call
decays exponentially with that count, floored above zero (never fully
trusted forever — an occasional re-check catches drift). Genuinely novel
phrasing always starts at probability 1.0 (always escalates) — the decay
is per-utterance-shape, not a blanket "the system is mature now" clock, so
new requests are never silently swallowed just because old ones decayed.

This composes with, rather than replaces, everything already local-first
in this repo:
- `crt-predict.py` — guesses the TEXT of an utterance before whisper
  finishes, from whole-utterance/bigram frequency.
- `bin/stt-fixups.json` — confirmed mis-hear → intent corrections
  (`"slide" → "claude"`, etc.) — a hand-curated, boolean "known" list.
- `crt-secretary.py`'s local-answer playbooks — resolve INTENT locally for
  a handful of known requests ("what's up" reads reports directly).

**What's new here is the middle layer**: not "what did they say" (predict)
or "is this a known mis-hear" (fixups) or "can I answer this without
Claude" (secretary) but **"how much more do I trust that I can handle THIS
utterance shape without Claude, given how many times I've handled it
before"** — a confidence score that grows with confirmed repetition and
should eventually gate whether the secretary's local path is even tried
before Claude gets a call at all.

## What's built (2026-07-21)

`bin/crt-stt-confidence.py` — the decision function only:
- `normalize_key(text)` — same normalization style as `stt-fixups.json`'s
  keys (lowercase, punctuation stripped).
- `call_probability(key, state)` — `INITIAL_P * DECAY_RATE ** confirmed_hits`,
  floored at `FLOOR_P`. Constants (`DECAY_RATE=0.55`, `FLOOR_P=0.03`) are a
  guess tuned to "small repeated vocabulary" (see `STT-MECHANISM.md`) — NOT
  measured against real traffic yet.
- `should_call_claude(text, state, rng)` — stochastic decision using the
  above probability (seeded `rng` for deterministic tests, real `random`
  module live).
- `record_confirmed(text, state)` / `record_claude_call(text, state)` —
  update persistent state (`~/.crt/stt-confidence.json`).

Unit-tested (`tests/test_stt_confidence.py`) against synthetic state, not
real history — same pattern as `test_predict.py`.

## Explicitly NOT done yet — and why

**Not wired into the live pipeline.** This is a decision function sitting
unused. Wiring it in means answering the open question below first —
doing it before that would just teach the system to be confidently wrong
faster, which is worse than the current "call Claude every time" default.

**Open question: what counts as "confirmed"?** `record_confirmed()` exists
but nothing calls it yet. Candidates, roughly in order of how much this
needs from further work:
1. **The user doesn't correct/repeat themselves** after a local (non-Claude)
   handling — implicit confirmation. Needs a way to detect "they just said
   nearly the same thing again," which is itself a small NLP problem.
2. **An explicit confirmation signal** — e.g. a control word ("yes"/"good")
   right after a local answer. Cheapest to build, worst UX (no one wants to
   say "confirmed" after every request).
3. **Claude, when it DOES get called, retroactively confirms** what the
   local path would have guessed — i.e. Claude call still happens, but the
   secretary compares its own local answer to Claude's actual response and
   records a hit only if they matched. This is the most honest signal (no
   new user burden, no guessing) but means the decay doesn't actually save
   any Claude calls until AFTER the comparison — the savings only show up
   once you start skipping the Claude call for high-confidence shapes, at
   which point you lose the comparison signal for those specific shapes.
   Likely needs periodic full re-verification (spend the floor probability
   deliberately, not just stochastically) to keep this signal alive.

**Not decided: per-exact-utterance vs semantic clustering.** Right now
`normalize_key` only merges utterances that are punctuation/case-identical
— "any reports for me" and "any reports for me today" are different keys
with independent decay. Given this room's genuinely small vocabulary (see
`STT-MECHANISM.md`), exact-key decay might already cover most real
repetition without needing embedding-based clustering — untested against
real `stt.log` history, worth checking before building anything fancier.

**Not decided: does this gate the secretary's local path, the Claude
call itself, or both?** The most conservative wiring: `should_call_claude`
only ever decides whether to TRY the local playbook first (never fully
skip Claude) — Claude stays the safety net. A more aggressive wiring
skips Claude entirely below the floor probability. Start conservative.

## Pick up next

1. Decide the confirmation signal (option 3 above is the most honest,
   least user-visible — start there if in doubt).
2. Wire `record_confirmed`/`record_claude_call` into `crt-secretary.py`'s
   actual routing, gated by a new opt-in flag (same convention as
   `CRT_SECRETARY`, default off) — do NOT change the live default behavior
   until this has real traffic behind it.
3. Once there's a few days of real `~/.crt/stt-confidence.json` history,
   revisit `DECAY_RATE`/`FLOOR_P` against how this room's vocabulary
   actually repeats (or doesn't).
