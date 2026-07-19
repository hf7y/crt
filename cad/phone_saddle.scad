// "phone" part: the saddle/cup that the handset barrel physically rests in.
// Snap-fits onto the boss on top of hook_lever.scad. Printed separately so
// you can re-print just this piece to tune fit against your actual handset
// without reprinting the whole lever.
include <params.scad>

module phone_saddle() {
  difference() {
    union() {
      // cradle trough, slightly more than half-pipe so the handset seats
      // positively and doesn't roll out
      translate([0, 0, handset_barrel_d/2])
        rotate([0, 90, 0])
          cylinder(d = handset_barrel_d + wall*2, h = handset_rest_len, center = true);

      // flat base so it sits flush on the lever boss
      translate([-handset_rest_len/2, -(handset_barrel_d/2 + wall), 0])
        cube([handset_rest_len, handset_barrel_d + wall*2, wall]);
    }
    // hollow out the trough itself
    translate([0, 0, handset_barrel_d/2 + wall])
      rotate([0, 90, 0])
        cylinder(d = handset_barrel_d, h = handset_rest_len + 2, center = true);

    // snap-fit socket for the lever boss (see hook_lever.scad lever_boss)
    translate([0, 0, -0.1])
      cylinder(d = 10 + clearance, h = wall + 0.2);
  }
}

phone_saddle();
