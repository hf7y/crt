// Simple wall/desk-mounted phone hook: handset hangs in a curved cradle by
// its own weight. A through-hole in the hook's neck is left for a hanging
// switch (reed switch + magnet, or a small lever microswitch) to be fitted
// later once you've picked the part — this file only reserves the hole.
// Distinct from cradle.scad/hook_lever.scad (the see-saw switch assembly);
// this is the low-effort "just hang it up" version.
include <params.scad>

hook_depth       = 40;   // how far the hook reaches under the handset barrel
hook_wall        = 6;
neck_w           = 26;
neck_h           = 30;
mount_hole_d     = 4.5;  // screw/bolt to the wall
switch_hole_d    = 8;    // reserved hole for hanging switch, drill/insert later
switch_hole_z    = 10;   // height up the neck where the hole sits

module wall_hook() {
  difference() {
    union() {
      // wall-mount backplate
      translate([-neck_w/2, -hook_wall, 0])
        cube([neck_w, hook_wall, neck_h]);

      // curved hook arm cradling the handset barrel
      translate([0, hook_depth/2, neck_h - handset_barrel_d/2])
        rotate([90, 0, 0])
          difference() {
            cylinder(d = handset_barrel_d + hook_wall*2, h = hook_depth, center = true);
            cylinder(d = handset_barrel_d, h = hook_depth + 2, center = true);
            // open the top third so the handset drops in/out
            translate([0, handset_barrel_d, 0])
              cube([handset_barrel_d*2, handset_barrel_d*2, hook_depth + 4], center = true);
          }
    }

    // two wall-mount screw holes
    translate([-neck_w/2 + 6, 0, 6])
      rotate([90, 0, 0]) cylinder(d = mount_hole_d, h = hook_wall + 2);
    translate([neck_w/2 - 6, 0, neck_h - 6])
      rotate([90, 0, 0]) cylinder(d = mount_hole_d, h = hook_wall + 2);

    // reserved hole for the hanging switch, installed later
    translate([0, 0, switch_hole_z])
      rotate([90, 0, 0]) cylinder(d = switch_hole_d, h = hook_wall + 2);
  }
}

wall_hook();
