// Grille + mount for a small dedicated speaker driving crt-earcon.sh's
// beeps (IDLE-BAIT.md / SIDETONE.md), separate from the handset earpiece
// -- the idea being the CRT itself gets a voice for non-verbal cues
// (beeps, chirps) distinct from anything that only plays through the
// phone. A round hole pattern over a speaker cavity, printable as a
// snap/screw insert into a project box or the CRT chassis.
//
// STATUS: pure speculative geometry -- no speaker purchased, no mounting
// surface measured. Placeholder shape to react to, not print-ready.
include <params.scad>

module earcon_grille() {
  plate_d = earcon_speaker_d + wall * 4;
  difference() {
    cylinder(d = plate_d, h = wall, $fn = 64);
    // concentric rings of small holes -- classic speaker-grille pattern
    for (ring = [0:2]) {
      r = (earcon_speaker_d / 2) * (ring + 1) / 3;
      n = 6 + ring * 6;
      for (i = [0:n-1]) {
        a = i * 360 / n;
        translate([r * cos(a), r * sin(a), -1])
          cylinder(d = earcon_grille_hole_d, h = wall + 2, $fn = 12);
      }
    }
    // center hole too
    translate([0, 0, -1]) cylinder(d = earcon_grille_hole_d, h = wall + 2, $fn = 12);
  }
}

earcon_grille();
