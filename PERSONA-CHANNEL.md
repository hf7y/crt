# Persona-channel indicator: mechanism decision

`cad/CAD-BACKLOG.md` flagged this as needing a mechanism decided before
any geometry gets written. Three options were on the table; this picks
one and says why, so it isn't re-litigated from scratch later.

## The options
**A. Servo-driven rotating disc** — a printed disc with an icon/color per
persona, a small servo rotates it behind a window when the system
switches persona.
**B. Static LED array** — one LED per persona behind a translucent icon,
GPIO-lit. No moving parts.
**C. Physical detented rotary switch** — an actual channel knob Chris
turns by hand (like an old TV selector). The switch's mechanical position
*is* the current persona; software reads it via GPIO, it doesn't set it.

## Decision: C, a real rotary switch, control and indicator are the same object
This is the one that actually fits the project's own stated principles
(`PHILOSOPHY.md`), not just the cheapest build:
- **#4 (verbs, not menus)**: turning a real knob to a real detent is a
  bodily decision with the same finality as lifting the handset. A or B
  make the *system* decide and merely display the result — that's a menu
  wearing a costume, not a verb.
- **#5 (one body, several selves)**: "changing the channel" should not be
  a metaphor implemented as an LED — it should be the literal channel
  knob, doing the literal thing. C is the only option where the metaphor
  and the mechanism are the same physical act.
- **No desync possible.** A/B require software state and physical display
  state to always agree — a crash, a stale process, or a race condition
  between "decided persona X" and "lit LED X" is a whole failure class C
  doesn't have. A detented switch's position is ground truth by
  construction; software reads it, never writes it. Simpler *and* more
  robust, not a tradeoff.
- **Works with the CRT off / power off.** A resting switch position is
  still legible (you can see/feel which detent it's in) even completely
  unpowered — consistent with `PARKING-LOT.md`'s RF-power-on vision where
  the device's resting state is meant to be inert, not a is powered
  standby display.

## What this means for the IR/RF idea in PARKING-LOT.md
The original pitch was the *system* changing the TV's channel via IR to
reinforce a persona switch it decided on its own. Under this decision,
causality flips: **Chris turning the physical knob is the trigger**, and
the system's job is to react (switch persona, optionally *also* fire the
IR blast to keep the TV's own channel in sync as a confirmation echo, not
as the thing that decided anything). This is a better fit for `PHILOSOPHY.md`
#2 (cost-of-ignoring near zero, nothing forced on him) — the system should
never unilaterally decide "you're now talking to the media-player persona,"
that's Chris's call, made with his hand, same standing as picking up the
phone at all.

## Rough mechanism
- An off-the-shelf **detented rotary switch** (4-6 position, like a
  cheap selector switch or a repurposed TV channel selector if one can be
  sourced) — not custom-printed detents, that's a solved, cheap,
  commodity part. GPIO reads the active position (Pi/microcontroller,
  simple digital-input-per-position or a binary-encoded version if
  position count grows).
- A printed **faceplate + knob skin** around the commodity switch is the
  actual CAD work — labeling/icon per position, sized to the switch's
  real shaft/bushing (needs the specific switch part chosen first, same
  measurement-before-geometry rule as the hookswitch assembly).
- Persona positions (draft, not final — Chris's call): secretary (default/
  home), media player, idle-bait/reports (a position that means "just
  tell me what's up," different from ambient idle-bait teasers), maybe a
  reserved unused position for whatever the gallery/payphone spinoffs
  teach us later.

## Status
Mechanism decided. **Switch part sourced 2026-07-20** —
https://www.amazon.com/dp/B088W8WMTB (linked directly in `BLOCKERS.md`).
Faceplate/knob CAD still blocked on that part's real dimensions once it's
in hand (measure it the same way the hookswitch assembly's parts get
measured — don't guess from the listing photos). Tracked in
`cad/CAD-BACKLOG.md`.
