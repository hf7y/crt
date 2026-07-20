// Shared measurements for the hookswitch assembly (handset / hook / cradle / switch).
// MEASURE YOUR ACTUAL HANDSET AND SWITCH AND EDIT THESE before printing —
// defaults are typical old-telephone-handset / generic microswitch dimensions.

// --- Handset ---
handset_barrel_d   = 34;   // diameter of the handset where it rests in the cradle prongs
handset_rest_len   = 60;   // length of barrel section that sits in the saddle

// --- Hook lever (see-saw pressed down by handset weight) ---
lever_length       = 70;
lever_width        = 22;
lever_thickness    = 5;
pivot_pin_d        = 4;    // diameter of the pivot rod/pin (e.g. M4 bolt or steel rod)
pivot_offset       = 20;   // distance from lever's front edge to the pivot axis

// --- Microswitch (generic mini SPDT lever switch, e.g. Omron V-15x / KW-11) ---
switch_body_w      = 12.8;
switch_body_d      = 6.4;
switch_body_h      = 6.4;
switch_mount_hole_spacing = 10;  // center-to-center of the two mounting screw holes
switch_screw_d     = 2.2;        // clearance hole for M2 self-tap

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
