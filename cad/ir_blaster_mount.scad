// Small bracket to aim an IR LED at the TV's remote sensor, for the
// "one body, several selves" persona-channel idea (PHILOSOPHY.md #5):
// switching mode = actually changing the TV's channel via IR, so each
// persona reinforces its own identity physically, not just on-screen.
//
// STATUS: pure speculative geometry -- no LED, no TV sensor position, no
// mounting surface measured yet. This exists so the idea has a shape to
// react to and refine once there's a real IR LED + TV in hand, not as a
// print-ready part.
include <params.scad>

module ir_blaster_mount() {
  difference() {
    union() {
      // base plate, mounts to the CRT chassis or a shelf near it
      cube([ir_mount_w, ir_mount_w, wall]);
      // angled LED holder, tilted toward the presumed TV sensor height
      translate([ir_mount_w/2, 0, wall])
        rotate([25, 0, 0])
          cylinder(d = ir_led_d + wall*2, h = ir_mount_h);
    }
    // LED bore through the holder
    translate([ir_mount_w/2, 0, wall - 0.5])
      rotate([25, 0, 0])
        cylinder(d = ir_led_d + clearance, h = ir_mount_h + 1);
    // two mount screw holes in the base plate
    translate([4, 4, -1]) cylinder(d = 3.4, h = wall + 2);
    translate([ir_mount_w - 4, ir_mount_w - 4, -1]) cylinder(d = 3.4, h = wall + 2);
  }
}

ir_blaster_mount();
