# Handset measurement guide

For Zach, next time the calipers (https://www.amazon.com/dp/B09R84QZ2P) are
actually in hand. One measurement per line in `params.scad` — take it,
report the number (or edit `params.scad` directly), done. No need to do
all of these in one sitting.

## Already real (2026-07-20, do not re-measure unless something changed)

- `handset_barrel_d` — neck/handle diameter, where the hand grips. 32.8mm.
- switch body / hole pitch — see `params.scad`'s microswitch block.

## Still a guess (2026-07-24) — `handset_overall_length`, `handset_earpiece_d`,
## `handset_mouthpiece_d`, `handset_weight_g`

Where to put the calipers/scale:

```
  earpiece                neck (measured)              mouthpiece
   ___                    ___________                     ___
  /   \                  /           \                   /   \
 | (A) |----------------| ===(D)=== |------------------| (B) |
  \___/        (C)        \_________/                    \___/
    ^                          ^                             ^
 ear cup dia.            handset_barrel_d              mouth cup dia.
 measured here           already measured here         measured here
 = handset_earpiece_d    (this is the "neck" you        = handset_mouthpiece_d
                          already calipered 2026-07-20)

  |<---------------------- (C) full length ---------------------->|
                    = handset_overall_length
```

- **(A) `handset_earpiece_d`** — caliper the widest point of the earpiece
  cup (the end that goes against your ear), straight across, outer
  diameter (outside of the plastic, not the speaker grille holes).
- **(B) `handset_mouthpiece_d`** — same, at the mouthpiece end. Often a
  touch smaller than the earpiece end; measure it separately, don't
  assume symmetry.
- **(C) `handset_overall_length`** — tip of earpiece cup to tip of
  mouthpiece cup, in a straight line (not following the curve of the
  handle) — this is what a tape measure or a long caliper gives you
  laid flat on a table next to the handset.
- **(D)** already done — `handset_barrel_d`, the neck/grip diameter. No
  action needed, just shown here for orientation.
- **`handset_weight_g`** — put the whole handset (cord unplugged if it
  detaches) on any kitchen/postal scale. Doesn't affect any geometry
  directly right now, only informs how stiff a return spring the
  see-saw lever needs — low priority, skip if the scale isn't handy.

## After measuring

Edit the four `GUESS` lines in `cad/params.scad`'s "full-body handset
dims" block, delete the word GUESS from each comment, then
`./export_stl.sh` to re-render anything downstream (currently only
`wall_hook.scad` derives from these; the hookswitch lever/saddle assembly
only needs `handset_barrel_d`, already real).
