// "cradle" part: the base body. Houses the pivot pin bosses for
// hook_lever.scad and a mounting pocket for switch_mount.scad, positioned
// so the lever's rear boss lands on the switch plunger at rest.
include <params.scad>

cradle_w = lever_width + wall*4;
cradle_l = lever_length + 10;
cradle_h = 22;

// switch_mount's base-plate footprint (must match switch_mount.scad)
switch_mount_w = switch_body_w + wall*2;
switch_mount_d = switch_body_d + wall*2;
socket_lip_h   = 3;      // height of the retaining rim, grips the base plate edge
socket_fit     = 0.3;    // interference: socket opening is footprint minus this

module cradle() {
  difference() {
    union() {
      // base
      translate([-pivot_offset - 5, -cradle_w/2, 0])
        cube([cradle_l, cradle_w, wall]);

      // pivot support walls, one each side, at x=0 (pivot axis)
      translate([-pivot_pin_d/2 - wall, -cradle_w/2, wall])
        cube([pivot_pin_d + wall*2, wall, lever_thickness + 10]);
      translate([-pivot_pin_d/2 - wall, cradle_w/2 - wall, wall])
        cube([pivot_pin_d + wall*2, wall, lever_thickness + 10]);
    }

    // pivot pin hole through both support walls
    translate([0, -cradle_w/2 - 1, wall + lever_thickness + 5])
      rotate([-90, 0, 0])
        cylinder(d = pivot_pin_d + clearance, h = cradle_w + 2);
  }

  // socket that switch_mount.scad's base plate press-fits into (no
  // screws). Position tuned so it's directly under hook_lever's rear
  // boss (at x = -pivot_offset + 8 in lever-local coords, pivot at x=0).
  translate([-pivot_offset + 8 - switch_mount_w/2, -switch_mount_d/2, wall])
    difference() {
      cube([switch_mount_w, switch_mount_d, socket_lip_h]);
      translate([socket_fit/2, socket_fit/2, -0.1])
        cube([switch_mount_w - socket_fit, switch_mount_d - socket_fit, socket_lip_h + 0.2]);
    }
}

cradle();
