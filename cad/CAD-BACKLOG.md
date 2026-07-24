# CAD backlog

Status of every part, existing and speculative. **2026-07-21: openscad now
installed**, `./export_stl.sh` renders everything clean. Benchy calibration
print done and confirmed fine — Ender 3 SD path is not a blocker anymore.

## Existing (hookswitch assembly, in progress per HANDOFF.md)
- `phone_saddle.scad`, `hook_lever.scad`, `switch_mount.scad`,
  `cradle.scad` — the see-saw hookswitch. **2026-07-20: real caliper
  measurements taken and plugged into `params.scad`** (handset neck
  32.8mm, switch body 12.9x5.7x6.2mm, hole pitch 6.0mm, lever ext 4.1mm).
  Unblocked for a first real render/print attempt. **2026-07-20**:
  `switch_mount.scad`/`cradle.scad` reworked to be screwless (no
  M-hardware on hand) — switch presses into its bracket by interference
  fit, bracket presses into a socket rim on the cradle base. Pivot pin
  still needs a 4mm rod (nail/filament/skewer work, not a screw).
  **2026-07-21: settled on pressure fit, `switch_screw_d` question moot**
  — no screws used anywhere in this assembly now. Still open:
  `switch_mount_h` (currently 14, in `switch_mount.scad`) needs physical
  tuning so the lever's rear boss fully depresses the plunger at rest —
  the height stack (base + switch body 6.2 + lever ext 4.1) hasn't been
  checked against the assembled lever/pivot yet. `phone_saddle.stl`
  renders with a "may not be 2-manifold" CGAL warning — cosmetic, slicers
  auto-repair on import, confirmed OK in slicer preview 2026-07-20.
- A Gemini-suggested alternate script (hanging wall-cradle instead of the
  see-saw lever) was considered this session and **not adopted** — Chris
  chose to keep the existing lever mechanism and feed it the real
  measurements instead. Note if revisiting: that script's mounting-pin
  translate math didn't line up with its own switch pocket (~3mm off),
  so it'd need a fix before use anyway.
- `wall_hook.scad` — simpler "just hang it up" alternative, reserved hole
  for a hanging switch. Same measurement dependency.
- `zach_hookswitch_cradle.scad` — **new 2026-07-21**, Chris-authored: a
  sphere/cylinder base with a switch pocket (interference-fit, same
  pressure-fit approach as the lever mechanism), unioned with an imported
  downloaded STL (`~/Downloads/Phone handset hook cradle - 3928257/files/
  Phone_Handset_Cradle_3.stl`). Renders clean. Not yet reconciled against
  the lever mechanism above — two live candidate designs right now, needs
  a decision once both are test-printed.

  **2026-07-24, re: BLOCKERS.md "caliper on hand, measurements not taken
  yet":** neck diameter (`handset_barrel_d`) and the switch were already
  real-calipered 2026-07-20, above — that blocker note was stale for
  those two. What's genuinely still ungauged is the *full-body* handset
  shape (overall length, earpiece/mouthpiece cup diameters, weight),
  which `wall_hook.scad` and this file's imported-STL union both touch.
  Per Zach's steer (handset "feels standard" in the hand — use an
  educated guess and an existing similar-handset STL rather than block):
  added `handset_overall_length`/`handset_earpiece_d`/
  `handset_mouthpiece_d`/`handset_weight_g` to `params.scad` as clearly-
  marked GUESS values sized off a typical corded handset (and consistent
  with the ~50mm scale this file's own imported reference STL already
  uses), and wired `wall_hook.scad`'s previously-hardcoded neck/hook
  numbers to derive from them instead of standalone magic numbers. The
  downloaded `Phone_Handset_Cradle_3.stl` referenced above **is** the
  "existing STL of a similar handset" for interim dev — already in the
  tree, no new sourcing needed. New `cad/HANDSET-MEASUREMENTS.md` has an
  ASCII diagram of exactly where to caliper each GUESS value once the
  B09R84QZ2P calipers are actually in hand; nothing here is blocking in
  the meantime.

## New this session (speculative, design-stage only)
- `ir_blaster_mount.scad` — bracket to aim an IR LED at the TV. **Parked
  2026-07-21** (see `PARKING-LOT.md`) — the blaster itself is now
  load-bearing again (drives the channel-confirmation loop below), but
  Chris is not building the physical case/mount right now. LED still
  sourced (https://www.amazon.com/dp/B099ZJ6555); TV sensor position
  still not measured either way.
- `earcon_grille.scad` — **abandoned 2026-07-21** — Chris: the TV has
  built-in sound, a dedicated beep-speaker on the CRT chassis isn't
  necessary. No speaker was ever bought, so nothing physical to undo;
  file can stay as dead reference or be deleted, Chris's call.

## Named but not yet stubbed (mechanism decided, part status noted)
- ~~Persona-channel indicator (rotary switch)~~ — **abandoned 2026-07-21**,
  see `PERSONA-CHANNEL.md`'s superseded note. Chris: use the CRT's actual
  TV channels instead of a separate switch — IR blaster emits the channel
  code to reinforce the active persona, TV's built-in speaker beeps a
  confirmation tone, handset mic picks it up to confirm the channel
  matched. Full idea in `PARKING-LOT.md`'s "Channel-confirmation loop."
  No faceplate/knob CAD needed; the previously-sourced switch
  (https://www.amazon.com/dp/B088W8WMTB) is no longer needed for this.
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

## Still blocked, physical
- Everything above needing "measure the real handset/switch" — cannot be
  advanced remotely.
