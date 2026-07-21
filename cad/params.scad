// Shared measurements for the hookswitch assembly (handset / hook / cradle / switch).
// Real caliper measurements taken 2026-07-20 (see CAD-BACKLOG.md) — no
// longer placeholders. switch_screw_d is still a guess (pin/screw size
// wasn't calipered); verify before drilling.

// --- Handset ---
// Measured handle neck width 32.8mm; +0.6mm printer clearance so the
// barrel doesn't bind in the trough (phone_saddle.scad cuts this exact dia).
handset_barrel_d   = 32.8 + 0.6;  // = 33.4
handset_rest_len   = 60;   // length of barrel section that sits in the saddle (not calipered — neck length, adjust if handset sits too shallow/deep)

// --- Hook lever (see-saw pressed down by handset weight) ---
lever_length       = 70;
lever_width        = 22;
lever_thickness    = 5;
pivot_pin_d        = 4;    // diameter of the pivot rod/pin (e.g. M4 bolt or steel rod)
pivot_offset       = 20;   // distance from lever's front edge to the pivot axis

// --- Microswitch (measured: 3-pin lever subminiature microswitch) ---
switch_body_w      = 12.9;   // body length (L)
switch_body_d      = 5.7;    // body width/thickness (W)
switch_body_h      = 6.2;    // body height (H), excludes pins & lever button
switch_lever_ext   = 4.1;    // lever extension above body top — clear this in switch_mount_h
switch_mount_hole_spacing = 6.0;  // measured mounting hole pitch
switch_screw_d     = 2.2;        // NOT calipered — guess for M2 self-tap, verify against actual pins

// --- IR blaster (persona/channel-switch signaling, see PHILOSOPHY.md #5) ---
ir_led_d           = 5;    // standard 5mm IR LED
ir_mount_w         = 20;
ir_mount_h         = 12;

// --- Earcon speaker (small dedicated driver for crt-earcon.sh beeps,
// separate from the handset earpiece -- see IDLE-BAIT.md) ---
earcon_speaker_d   = 28;   // typical small round speaker (e.g. 28mm mini driver)
earcon_grille_hole_d = 2;
earcon_grille_hole_spacing = 4;

// --- General ---
wall               = 3;
clearance          = 0.3;  // fit clearance between mating printed parts
$fn                = 48;
