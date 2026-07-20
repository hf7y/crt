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

## The load-bearing legal question — settle this FIRST
**A machine that accepts real coins and sometimes pays out more coins/
value than inserted is, depending on jurisdiction, a gambling device**,
regardless of artistic intent. This isn't a minor compliance footnote —
it can determine whether the piece is legal to operate at all in a given
venue/state, and rules vary a lot by jurisdiction (games of skill vs.
chance, prize value caps, whether it's sited in a licensed venue, etc.).
**Do not build the real-payout version without an actual legal check for
the specific venue/jurisdiction.** Recommended default, and the version
this brief scopes below: **no real-money payout, ever.** The "sometimes
gives more back than inserted" mechanic is scoped entirely in-world (see
below) — genuinely safer, and arguably a better piece for it (the
surprise/generosity is about *attention and conversation*, not cash).

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

## Scope (draft, assuming the safe framing above)
1. **Coin acceptor**: a standard commercial coin mechanism (e.g. a
   Coinco/Mars-style validator, common in arcade/vending — off-the-shelf,
   not custom-built) wired to a simple GPIO pulse-counter (Pi or
   microcontroller). Accepts real quarters as a "play" trigger only —
   never dispenses them back.
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
1. Confirm the no-real-payout framing is acceptable creatively, or if a
   real-payout version is actually wanted — if the latter, **stop and get
   real legal advice for the specific venue before building anything**,
   this brief does not scope that version.
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
Design brief only. No venue, no budget, no build started. The legal
framing question is the one thing to nail down before any other work on
this concept, including hardware sourcing.
