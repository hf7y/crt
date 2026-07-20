# RFP (design brief): payphone token-economy installation

Fleshes out `PARKING-LOT.md`'s payphone concept. Not started; no venue/
budget attached. Distinct project from `crt` and from `RFP-GALLERY.md` —
shares handset/audio DNA, not a backend.

## One-line pitch
A real payphone people actually put quarters into. Coin mechanism routes
to a TTS/AI backend that "does something" — answers questions, has a
conversation. Stretch: a token economy where it sometimes gives back more
than was inserted, turning it into more of a game/gamble than a vending
transaction.

## The load-bearing legal question — RESOLVED 2026-07-20
Confirmed direction: **real coin-operated mechanism, quarters as the
prototyping currency, no real payout, never deployed for real money.**
Specifically —
- Build/test against a **real coin-operated mechanism that takes
  quarters** — quarters are just the most available physical token for
  prototyping, not a monetary design choice.
- Target end-state is **token-only** (swap the mechanism to accept custom
  tokens instead of quarters) *if that conversion turns out to be easy*.
  If not easy, keep testing/developing on the quarter mechanism while the
  token conversion proceeds as a **parallel work stream**, not a blocker
  on everything else.
- **No legal check needed under this framing** — explicitly confirmed,
  because this is never deployed as a live/public installation using real
  money. The original concern below (a machine that accepts real coins
  and pays out more value than inserted is, in many jurisdictions, a
  gambling device) only applies to a genuine public real-money deployment,
  which this project isn't and won't be. Kept here as background for why
  the framing matters, not as an open blocker anymore.

The "sometimes gives more back than inserted" mechanic is still scoped
entirely in-world (see below), independent of the quarters-vs-tokens
question — even in the confirmed no-real-money framing, coins/tokens
inserted are still consumed, not refunded as coins/tokens; what comes
back is conversation time, a printed fortune, or a collectible token.

## Recommended framing (avoids the legal cliff entirely)
- Coins/tokens are **consumed**, not refunded as coins. What comes back
  out is never currency:
  - **More conversation time** — the generous outcome is "keep talking,
    this one's on the house," not a coin return.
  - **A physical takeaway** — a printed fortune/receipt (reuse the
    Phomemo printer pattern from `SECRETARY.md`'s printer channel) is a
    much safer "prize" than money, and ties this into the same hardware
    already in the personal-crt project.
  - **A collectible token** (custom-minted, worthless outside the
    installation, explicitly non-redeemable) if a physical "you won
    something" moment is wanted — common, legal, arcade-token pattern.
- This preserves the "sometimes generous" game feel Chris described
  without the regulatory risk of a real-money payout mechanism.

## Scope (draft, assuming the confirmed framing above)
1. **Coin acceptor**: a standard commercial coin mechanism (e.g. a
   Coinco/Mars-style validator, common in arcade/vending — off-the-shelf,
   not custom-built) wired to a simple GPIO pulse-counter (Pi or
   microcontroller). **Build/test phase: accepts real quarters** as a
   "play" trigger only, never dispenses them back. **Parallel track**:
   evaluate whether the same validator (or a compatible one) can be
   reconfigured/re-calibrated to accept custom tokens instead of quarters
   — many commercial validators support this via coin-size/weight
   profiles — and if so, migrate to token-only once that's sorted,
   without blocking build progress on quarters in the meantime.
2. **Handset + hookswitch**: reuse the `cad/` assembly design directly,
   this is the same mechanical problem as the personal crt.
3. **Backend**: a conversational TTS/AI backend, much closer to the
   personal `crt`'s secretary ambitions than the gallery piece's simple
   message-store — this one's meant to actually talk back. Could
   literally reuse `bin/crt-tts.py` + a scoped Claude-Code-or-similar
   backend, with a payphone-specific persona (a "hello, thanks for the
   quarter" character, not the personal secretary's voice).
4. **The "generosity" mechanic**: a simple weighted-random or rule-based
   decider (e.g. 1-in-5 calls get bonus time / a printed fortune) — cheap
   to build, the actual creative tuning (odds, what "generous" looks/
   sounds like) is a content-design task, not an engineering one.
5. **Coin-return mechanical fallback**: even without a payout mechanic,
   a real coin acceptor should still have its **standard manual coin
   return lever** (for jammed/rejected coins) — that's a mechanical
   safety/usability feature of the coin validator itself, unrelated to
   the payout question above; don't skip it.

## Open questions (need the artist, not guessed here)
1. ~~Confirm the no-real-payout framing~~ **ANSWERED 2026-07-20** — see
   the resolved legal section above.
2. What's the actual conversation? A fixed bit (payphone has a
   personality/backstory, canned-ish responses) vs. genuinely open Claude-
   Code-backed conversation (higher cost per call, higher variance,
   possibly higher liability for what a stranger might get the machine to
   say in a public space — content-moderation question, same as
   `RFP-GALLERY.md`'s #3).
3. Physical: real payphone shell (charm, sourcing/weight/cost) vs.
   reproduction. Real ones are heavy commercial-grade steel enclosures —
   good for public durability, bad for portability/budget.
4. Per-call cost ceiling if it's backed by a hosted model — a public,
   unattended, coin-triggered device calling out to a paid API needs a
   hard spend cap/kill-switch, not just a rate limit.

## Explicitly out of scope for v1
- Any real-money payout mechanism (see legal section above).
- Multi-unit/networked behavior (this is a single-unit piece, unlike
  `RFP-GALLERY.md`).

## Status
Design brief, direction confirmed 2026-07-20 (quarters for prototyping,
token conversion in parallel, no legal blocker under this framing). No
venue, no budget, no build started yet — but unlike before, hardware
sourcing (a real coin validator) is no longer blocked on an open
decision.
