# CAD backlog

Status of every part, existing and speculative. Render check: none of this
has been run through `openscad` yet in this session (not installed in this
environment) — syntax is hand-verified against the existing working files'
style, not compiler-verified. Run `./export_stl.sh` and eyeball each part
before printing anything.

## Existing (hookswitch assembly, in progress per HANDOFF.md)
- `phone_saddle.scad`, `hook_lever.scad`, `switch_mount.scad`,
  `cradle.scad` — the see-saw hookswitch. **Blocked on measuring the real
  handset barrel + microswitch** (`params.scad` has generic placeholders,
  explicitly flagged there) — physical, needs Chris's hands, not
  advanceable remotely. **2026-07-20**: caliper on hand (a specific one
  linked in `BLOCKERS.md`), measurements not taken yet — closer than
  before, still blocked on the actual numbers.
- `wall_hook.scad` — simpler "just hang it up" alternative, reserved hole
  for a hanging switch. Same measurement dependency.

## New this session (speculative, design-stage only)
- `ir_blaster_mount.scad` — bracket to aim an IR LED at the TV, for the
  persona/channel-switch idea (`PHILOSOPHY.md` #5) and the TV-power-on
  trigger (`PARKING-LOT.md`, corrected from RF to IR 2026-07-20 — one
  blaster likely covers both jobs). **IR LED sourced 2026-07-20**:
  https://www.amazon.com/dp/B099ZJ6555 — TV sensor position still not
  measured, mount geometry stays placeholder until it's in hand.
- `earcon_grille.scad` — speaker grille for a dedicated beep-speaker on
  the CRT chassis itself (see `IDLE-BAIT.md`/`SIDETONE.md`), separate
  from the handset earpiece — the console gets its own non-verbal voice
  independent of anything routed through the phone. No speaker bought.

## Named but not yet stubbed (mechanism decided, part status noted)
- **Persona-channel indicator** — mechanism decided in `PERSONA-CHANNEL.md`
  (2026-07-19): a real detented rotary switch Chris turns by hand, control
  and indicator are the same object, no servo/LED display to desync.
  **Switch sourced 2026-07-20**: https://www.amazon.com/dp/B088W8WMTB —
  still not stubbed pending real dimensions once it arrives (shaft/
  bushing) — the CAD work is a faceplate/knob skin around that part, same
  measure-first rule as the hookswitch.
- **HDMI-to-RF multi-channel modulator housing** (`PARKING-LOT.md`'s
  multi-persona TV-channel idea) — **the modulator itself is already
  owned** (2026-07-20, supports daisy-chain multi-channel) — this is no
  longer a sourcing blocker, just an unstubbed housing/mounting/wiring
  integration task. Worth a first stub once its physical footprint is in
  hand to measure.
- **Handset internal mic/earpiece wiring harness** — implied by
  `SIDETONE.md`'s recommendation to design passive hardware sidetone
  *into* the handset wiring from the start, rather than retrofitting.
  Not geometry yet, but flagged here so it isn't designed twice — the
  hookswitch assembly and the audio wiring should be planned together
  once real hardware is in hand.

## Unrelated to the personal crt, tracked here anyway since they're CAD
- `RFP-GALLERY.md` / `RFP-PAYPHONE.md` will need their own hardware once
  (if) either moves past the brief stage — a gallery unit reuses the
  hookswitch assembly design directly; the payphone brief explicitly
  recommends off-the-shelf coin-mechanism hardware, not custom CAD, so
  its only new part is likely a mounting bracket for that mechanism once
  a specific validator model is chosen.

## Still blocked, physical, unchanged from before this session
- Benchy calibration print (Ender 3 SD path needs verifying).
- Everything above needing "measure the real handset/switch" — cannot be
  advanced remotely; this session did not attempt to.
