// ========================================================
// HANGING HOOKSWITCH CRADLE FOR SUBMINIATURE LEVER SWITCH
// Gemini-suggested alternate design, not adopted (see CAD-BACKLOG.md) —
// kept here verbatim for reference/comparison against the lever mechanism.
// Known issue, not fixed: the mounting-pin translate math doesn't line up
// with the switch pocket it's meant to pin into (~3mm off in Y).
// ========================================================

$fn = 100; // Smooth curves

// --- HANDSET MEASUREMENTS ---
earpiece_d   = 60.9 + 1.6; // 62.5 mm cup ID
handle_w     = 32.8 + 2.2; // 35.0 mm front slot
cup_height   = 25.0;

// --- MICROSWITCH MEASUREMENTS ---
sw_L = 12.9 + 0.3; // 13.2 mm
sw_H = 6.2 + 0.2;  // 6.4 mm
sw_W = 5.7 + 0.2;  // 5.9 mm
sw_pitch = 6.0;

// --- MODULE: MAIN HOOK CRADLE ---
module hanging_cradle() {
    difference() {
        // Main outer body block
        union() {
            cylinder(d = earpiece_d + 10, h = cup_height);
            translate([- (earpiece_d + 10)/2, 0, 0])
                cube([earpiece_d + 10, (earpiece_d + 10)/2 + 15, cup_height]);
        }

        // Inner cup for earpiece
        translate([0, 0, 5])
            cylinder(d = earpiece_d, h = cup_height);

        // Front pass-through slot for handle neck
        translate([-handle_w/2, -(earpiece_d + 20)/2, -1])
            cube([handle_w, earpiece_d, cup_height + 2]);

        // Internal Pocket for Tiny Switch
        translate([-sw_L/2, (earpiece_d/2) - 2, 5])
            cube([sw_L, sw_W, sw_H + 2]);

        // Wiring / Pin clearance slot beneath switch
        translate([-sw_L/2, (earpiece_d/2) - 2, 0])
            cube([sw_L, sw_W, 6]);
    }

    // Tiny mounting pins for 6mm pitch switch holes
    translate([-sw_pitch/2, (earpiece_d/2) + (sw_W/2) - 2, 8])
        rotate([90, 0, 0]) cylinder(d=1.8, h=sw_W);
    translate([sw_pitch/2, (earpiece_d/2) + (sw_W/2) - 2, 8])
        rotate([90, 0, 0]) cylinder(d=1.8, h=sw_W);
}

hanging_cradle();
