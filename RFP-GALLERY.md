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

## Architecture possibilities (2026-07-20, requested writeup)
Direction given: explore per-unit-Raspberry-Pi (centralized or autonomous)
vs. real POTS wiring through a switcher, "from a possibilities standpoint
— what do different choices make possible." Three real options, not two —
the original "centralized vs. independent" framing below undersells it:

**A1 — Per-unit Pi, centralized backend** (the original draft above).
Each phone has its own compute, but all logic/storage lives on one
central server; units are thin clients. Gets WiFi-only deployment (no
cabling) and per-unit hardware uniformity, but inherits a single point of
failure (the central server) AND N units' worth of hardware cost — worth
naming that this option is dominated by A2 or B below on most axes: it
doesn't get A2's resilience/personality upside, and doesn't get B's cost
advantage.

**A2 — Per-unit Pi, autonomous/networked** (the leaning, per direction
given). Each Pi runs its own message logic and personality, and units
talk to each other peer-to-peer (or over a lightweight shared bus like
MQTT) rather than through one brain. What this makes possible:
- **Genuine per-unit character** — each phone's STT quirks, voice, and
  local message queue could actually differ, closer to `PHILOSOPHY.md`
  #6 (imperfection is character) applied at installation scale: not
  identical terminals, actual distinct beings.
- **Failure isolation** — one Pi crashing doesn't take the show down; the
  others keep working. Directly answers the original brief's stated top
  risk ("far more reliable for an unattended multi-day show").
  Independent units *already* had this property in the original framing
  — autonomous-but-networked keeps it while adding the message-hopping
  magic independent units lacked.
  - **Emergent message propagation** — a message could genuinely "wander"
  the room over time (gossip-protocol style) rather than "leave at A,
  mystery unit B rings" being the only shape — a substantially more
  interesting mechanic than the original pitch, and one only this
  architecture makes possible.
- Costs: N Pis' worth of hardware and N images/configs to keep alive
  across a multi-day show — real per-unit maintenance burden, and the
  gossip/message-propagation design itself needs real creative work, not
  just engineering.

**B — Real POTS wiring through a switcher.** Visitors' handsets are real
dumb analog phones; a small PBX/FXS-FXO switch (or simple key-telephone
hardware) does all the compute centrally, real wiring runs to each unit.
What this makes possible:
- **Much lower per-unit cost** — a real analog handset is $5-20 secondhand,
  zero compute per phone. At any real N, this is the cheap option.
- **Authentic feel** — real electromechanical ringing, real handset
  weight/acoustics, closer to "an old phone system," not "a Pi in a
  shell." The wiring itself (visible conduit runs, or hidden-in-the-walls)
  is part of the aesthetic either way, a real installation-design choice.
- **One STT/TTS instance to run**, not N — simpler audio pipeline, though
  it costs A2's per-unit-personality upside unless deliberately varied
  per line in software.
- Costs: a real single point of failure (the switch going down takes
  every phone out at once — worse than A2, though only one machine to
  babysit instead of N), and physical cable runs across the venue, a real
  logistics/venue constraint A2's WiFi-only deployment doesn't have.

**Report summary**: A2 (autonomous networked Pis) and B (POTS+switcher)
are the two real choices — they optimize for different things (character/
resilience/no-cabling vs. cost/authenticity/simplicity) and neither
dominates the other. A1 is likely not worth pursuing on its own terms.
This is exactly the kind of call that should wait for a real venue/budget
(same "don't over-invest before this is answered" note as before) — but
now it's a three-way creative choice, not an engineering default.

## Open questions (need the artist/curator, not guessed here)
1. **Which architecture — A2 (autonomous Pis) or B (POTS+switcher)?**
   See the possibilities writeup above. This is still the single
   highest-leverage decision — settle it before any hardware is bought.
   > A2 is best. Park B for now. Okay to reference in later docs when
   > moments relevant to B emerge (B would do this idea more cleanly,
   > B would need x, y, z to implement that) for future reference.

2. Does a visitor ever get an AI-generated reply, or is this pure
   human-to-human (visitor leaves a message, another visitor hears it,
   nothing synthetic in between)? Pure human-to-human is simpler, more
   reliable, and arguably a stronger piece — but "sometimes something
   answers back" has its own appeal. Pick one on purpose.
   > Pure human-to-human is simpler. In fact, the project should uphold
   > the princple that humans only ever hear real human speech, never
   > true AI generation. should aim for high compliance on this but 
   > leave the door open to some AI processing of speech for cleanliness,
   > explitive filtering, pacing etc.

3. Content moderation — a public gallery phone that records strangers is
   a real liability/consent question (recording anonymous visitors' voices
   in a public space). Needs a real answer (signage? opt-in? no raw-audio
   retention, transcript only? auto-delete after the show?) before this
   is buildable, not an afterthought.
   > We'll go with signage: explicit disclaimer that one is being recorded
   > along with auto-delete promises. Voice recordings are bound to the
   > show's duration.

4. Physical: real vintage handsets (charm, but fragile/expensive/hard to
   source N of) vs. reproduction/3D-printed shells (cheap, consistent,
   less charm) — budget-dependent, revisit once N and venue are known.
   > This will be budget dependent based on actual funding. Let's develop
   > independent from this with paralell solutions for now. End result
   > may be a mix of both. Cheap solution needs to exist as fall back
   > but POTS version is aspiration.

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
