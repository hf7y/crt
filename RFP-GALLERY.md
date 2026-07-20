# RFP (design brief): distributed answering machines, gallery installation

Fleshes out `PARKING-LOT.md`'s gallery concept into something a
fabricator/collaborator could actually scope. Not started; no budget or
venue attached yet — this is the brief to have *ready* when one shows up.
Distinct project from the personal-secretary `crt` — shares code DNA
(handset, STT/TTS, hookswitch), not a backend or persona.

## One-line pitch
Multiple old-phone units scattered through a gallery space. Visitors leave
messages for whoever finds them next, or pick up and hear whatever's
waiting. Phones physically ring when something's waiting for them.

## Why this is a different beast from the personal crt
- **Multi-unit, not single-unit.** Needs a shared backend (or a
  deliberately-chosen *lack* of one — see open question below) so a
  message left at phone A can surface at phone B.
- **Visitor-facing, not owner-facing.** No STT-accuracy tuning for one
  known voice/room — many voices, many accents, one-shot interactions
  (a visitor won't tolerate "sorry, say that again" the way Chris will).
  Bar for graceful degradation is much higher.
- **Unattended for hours at a time**, gallery-open hours, no one around to
  restart a hung process. Needs to be boringly reliable, not clever.
- **No secretary/Claude Code brain required** — this is closer to an
  installation piece than an assistant. Simpler backend, more emphasis on
  the physical/sound design.

## Scope (draft)
1. **N phone units** (N TBD by venue — 3-5 is a reasonable first
   installation size). Each: a real or repurposed handset + hookswitch
   (reuse `cad/` hookswitch assembly design, cheap microswitch, no CRT
   needed per-unit — a phone is just a phone here, no screen).
2. **Per-unit hardware**: cheapest viable compute (a Pi Zero 2 W class
   device per phone is plausible — no local whisper needed if STT is
   centralized, see below), USB audio interface for the handset, a
   physical **ringer** (real bell/solenoid, not a speaker beep — this
   should sound and feel like an old phone ringing, that's the whole
   point).
3. **Central backend** (one machine, e.g. a Pi or small server in a closet/
   booth): receives audio from any unit, does STT + storage, decides
   which unit(s) should ring next and with what. A message store is just
   "who left it, which unit picked it up, transcript, audio file,
   timestamp" — deliberately simple, no AI response generation needed
   unless the piece wants one (open question).
4. **Network**: units need to reach the central backend — venue wifi
   (fragile, gallery walls) or a private mesh/wired run installed for the
   show. **This is probably the single biggest practical risk** — decide
   early, budget for it, don't assume venue wifi will just work.
5. **Ringing logic** (the actual "installation" behavior, worth designing
   deliberately, not defaulting to "ring whoever's next in a queue"):
   - Random unit rings some time after a message is left — feels alive,
     unpredictable, matches "visitors receive messages" framing.
   - Or: a specific unit rings only when *that* unit's own message queue
     has something — feels more like a real mailbox per phone.
   - Or: pick both — most left-messages go to a random unit (mystery/
     surprise), but a phone can also "remember" and re-ring its own queue
     if unanswered. Needs a real creative decision, not an engineering
     default.

## Open questions (need the artist/curator, not guessed here)
1. **Centralized backend vs. fully independent units?** Independent units
   (no shared network at all, no message hand-off between phones) are
   far more reliable for an unattended multi-day show and have zero
   network-risk — but lose the "leave a message, a stranger picks it up
   elsewhere in the room" magic that's the whole pitch. This is the
   single highest-leverage design decision — settle it before any
   hardware is bought.
2. Does a visitor ever get an AI-generated reply, or is this pure
   human-to-human (visitor leaves a message, another visitor hears it,
   nothing synthetic in between)? Pure human-to-human is simpler, more
   reliable, and arguably a stronger piece — but "sometimes something
   answers back" has its own appeal. Pick one on purpose.
3. Content moderation — a public gallery phone that records strangers is
   a real liability/consent question (recording anonymous visitors' voices
   in a public space). Needs a real answer (signage? opt-in? no raw-audio
   retention, transcript only? auto-delete after the show?) before this
   is buildable, not an afterthought.
4. Physical: real vintage handsets (charm, but fragile/expensive/hard to
   source N of) vs. reproduction/3D-printed shells (cheap, consistent,
   less charm) — budget-dependent, revisit once N and venue are known.

## Explicitly out of scope for v1
- Any AI personality/secretary behavior (that's the personal `crt`'s job).
- Remote/off-site message leaving (phone-only, in-person, gallery hours
  only).
- Payment/token mechanics (that's `RFP-PAYPHONE.md`, a separate concept).

## Status
Design brief only. No venue, no budget, no build started. Revisit once an
actual installation opportunity exists — don't over-invest in hardware
sourcing before question 1 (centralized vs. independent) is answered, it
changes the entire bill of materials.
