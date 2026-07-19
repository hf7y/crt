// "hook" part: see-saw lever. Handset weight on the front (phone_saddle end)
// pushes the lever down; the rear underside boss presses the microswitch
// plunger. Lifting the handset lets a spring (or the switch's own return
// spring) rock it back up.
include <params.scad>

module hook_lever() {
  difference() {
    union() {
      // main beam
      translate([-pivot_offset, -lever_width/2, 0])
        cube([lever_length, lever_width, lever_thickness]);

      // boss on top, front end, for phone_saddle to snap onto
      translate([lever_length - pivot_offset - 15, 0, lever_thickness])
        cylinder(d = 10 - clearance, h = 4);

      // boss on underside, rear end, that contacts the switch plunger
      translate([-pivot_offset + 8, 0, -6])
        cylinder(d = 6, h = 6);
    }

    // pivot pin hole, through the beam at x=0
    translate([0, 0, lever_thickness/2])
      rotate([90, 0, 0])
        cylinder(d = pivot_pin_d + clearance, h = lever_width + 2, center = true);
  }
}

hook_lever();
