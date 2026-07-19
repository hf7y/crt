// "switch" part: bracket holding a mini SPST/SPDT microswitch directly
// under the hook_lever's rear boss, at the height where the lever's
// resting (handset-down) position just fully depresses the plunger.
include <params.scad>

switch_mount_h = 14;  // tune so plunger sits exactly under the lever boss at rest

module switch_mount() {
  difference() {
    union() {
      // base plate, screws down into the cradle body
      cube([switch_body_w + wall*2, switch_body_d + wall*2, wall]);

      // side walls holding the switch body at height
      translate([0, 0, 0])
        cube([wall, switch_body_d + wall*2, switch_mount_h]);
      translate([switch_body_w + wall, 0, 0])
        cube([wall, switch_body_d + wall*2, switch_mount_h]);
    }

    // mounting screw holes for the switch itself, on the two side walls
    translate([wall/2, wall + switch_body_d/2 - switch_mount_hole_spacing/2, switch_mount_h - 3])
      rotate([0, 90, 0]) cylinder(d = switch_screw_d, h = wall + 1);
    translate([wall/2, wall + switch_body_d/2 + switch_mount_hole_spacing/2, switch_mount_h - 3])
      rotate([0, 90, 0]) cylinder(d = switch_screw_d, h = wall + 1);
    translate([switch_body_w + wall/2, wall + switch_body_d/2 - switch_mount_hole_spacing/2, switch_mount_h - 3])
      rotate([0, 90, 0]) cylinder(d = switch_screw_d, h = wall + 1);
    translate([switch_body_w + wall/2, wall + switch_body_d/2 + switch_mount_hole_spacing/2, switch_mount_h - 3])
      rotate([0, 90, 0]) cylinder(d = switch_screw_d, h = wall + 1);

    // base screw holes to fasten bracket into the cradle body
    translate([wall/2, wall/2, -0.1]) cylinder(d = switch_screw_d, h = wall + 0.2);
    translate([switch_body_w + wall*1.5, switch_body_d + wall*1.5, -0.1]) cylinder(d = switch_screw_d, h = wall + 0.2);
  }
}

switch_mount();
