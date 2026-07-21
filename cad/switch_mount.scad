// "switch" part: bracket holding a mini SPST/SPDT microswitch directly
// under the hook_lever's rear boss, at the height where the lever's
// resting (handset-down) position just fully depresses the plunger.
//
// Screwless version (2026-07-20, no M-hardware on hand): the switch body
// is held by an interference (press) fit between the two side walls
// instead of screwed tabs, and the bracket's own base plate press-fits
// into a socket cut in cradle.scad instead of being screwed down. If it's
// ever too loose/tight, adjust switch_press_fit / cradle_socket_fit below
// rather than re-adding screw holes.
include <params.scad>

switch_mount_h = 14;  // tune so plunger sits exactly under the lever boss at rest
switch_press_fit = 0.3;  // interference: side-wall gap is switch_body_w minus this

module switch_mount() {
  // base plate — press-fits into the socket in cradle.scad, no screws
  cube([switch_body_w + wall*2, switch_body_d + wall*2, wall]);

  // side walls holding the switch body by friction; gap is slightly
  // narrower than the switch so it has to be pressed in
  translate([0, 0, 0])
    cube([wall + switch_press_fit/2, switch_body_d + wall*2, switch_mount_h]);
  translate([switch_body_w + wall - switch_press_fit/2, 0, 0])
    cube([wall + switch_press_fit/2, switch_body_d + wall*2, switch_mount_h]);
}

switch_mount();
