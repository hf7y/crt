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

## Wired in, 2026-07-21 — steps 1-2 done

Picked **option 3** (Claude retroactively confirms) — it's the only one
that needs nothing new from the user. `crt-secretary.py` now has:
- Every playbook handler returns its spoken/summary text (previously
  side-effect-only), giving `confidence_route()` something to compare
  against.
- `confidence_route(text, action)` — runs the matched playbook exactly as
  before (never delayed, never skipped), then, only when
  `CRT_SECRETARY_CONFIDENCE=1` (default OFF, same convention as
  `CRT_SECRETARY`), kicks off `_confirm_in_background()` in a daemon
  thread so the live Claude round-trip (up to `CLAUDE_MAX_WAIT` seconds)
  never blocks the caller — the user already has their answer by the
  time this even starts.
- `_confirm_in_background()` — per `should_call_claude`'s decaying
  probability, sometimes fires a real (but silent — never spoken/shown)
  Claude call for the same utterance, compares it against the local
  playbook's answer via `_answers_match()` (loose substring-either-way
  match, explicitly a first draft, not real semantic equivalence), and
  records `confirmed_hits`/`claude_hits` accordingly.
- **This wiring alone saves ZERO Claude calls** — with the flag on, a
  matched playbook still runs Claude in the background at the same rate
  `should_call_claude` would have called it anyway; it only starts
  *tracking* confirmation data. That's intentional per the doc above:
  skip-Claude-below-the-floor is a separate, later, more aggressive step
  once real `~/.crt/stt-confidence.json` history exists to justify it.
- Tests: `tests/test_secretary.py`'s `TestAnswersMatch`/
  `TestConfidenceRouting` (9 new cases), default-off path verified to be
  byte-identical to the pre-wiring behavior.

## Pick up next

1. ~~Decide the confirmation signal~~ **DONE above.**
2. ~~Wire into `crt-secretary.py`~~ **DONE above.**
3. Turn `CRT_SECRETARY_CONFIDENCE=1` on for a live session and let real
   traffic accumulate in `~/.crt/stt-confidence.json` — needs a human on
   `crt-vm`, not buildable further from an unattended pass.
4. Once there's a few days of real history, revisit `DECAY_RATE`/
   `FLOOR_P` against how this room's vocabulary actually repeats (or
   doesn't), and design the actual skip-Claude-below-floor step.
