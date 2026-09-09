# Display calibration: the overscan game

The VM's default graphical output **overshoots** the CRT's visible area
(the tube's bezel/overscan crops the edges of a normal 4:3 signal — this
is completely normal CRT behavior, not a bug in the VM), but forcing an
800x600 mode **undershoots** (leaves the picture smaller than the tube can
actually show, wasting real visible area). Neither raw setting is right;
what's needed is the classic broadcast-TV answer to exactly this problem:
a **safe area** — content deliberately kept inside a margin that's
guaranteed visible regardless of the exact overscan on this specific tube
— plus, if possible, dialing the VM's actual output resolution closer to
right in the first place.

## Two independent levers, don't conflate them
1. **VirtualBox display resolution** (host-level, e.g. `VBoxManage
   setextradata`/guest additions custom mode) — the "real" fix, gets more
   of the signal actually inside the visible tube. **Needs dexter access
   to test** — not buildable this session.
2. **Software safe-margin inset** (this repo, works regardless of #1) —
   every renderer (`crt-pager.py`, `crt-monologue.sh`, the calibration
   pattern itself) insets its content by a configured margin, so even an
   imperfect resolution choice never *clips actual content*, only wastes
   some blank border. This is the one built this session, and it's the
   one that matters more: #1 can only ever get you *close*, given a fixed
   discrete set of resolutions vs. a continuously-variable real tube;
   #2 is what actually guarantees nothing important gets cut off.

## The calibration "game" (a ritual mode, per Chris's framing)
Consistent with `PHILOSOPHY.md` #4 (verbs, not menus): calibration should
feel like a small interactive game played over the handset, not a menu of
numeric settings. The shape:
1. Render a test pattern: a numbered ruler along all four edges, a letter
   in each corner, at the **current** safe-margin guess.
2. Ask, by voice: "can you see the letter in every corner? which ones
   are cut off?"
3. Chris answers by voice ("top right is gone" / "all four are fine" /
   "the whole left edge is cut off"). STT parses this into a per-edge
   cut-off/ok signal.
4. Adjust: any cut-off edge grows its margin (pull content further in);
   any consistently-fine edge shrinks its margin a little (reclaim
   wasted border) — a simple hill-climb, not a search algorithm, because
   the actual physical crop doesn't change between rounds, so a few
   rounds of "grow what's cut, shrink what's fine" converges fast.
5. Repeat until Chris says it looks right, or a round changes nothing
   (converged). Save the result to `~/.crt/display.conf`.
6. Every renderer reads that margin from then on.

## Shipped, and what's still a guess
`bin/crt-calibrate-display.py` (`render_pattern`/`adjust_margins`/
`load_display_conf`/`save_display_conf`, each documented at its own
definition) implements the ritual above; `crt-pager.py` and
`crt-monologue.sh` read the saved margin on every render
(`load_display_margins`/`apply_margins`). Covered by
`tests/test_calibrate_display.py` (the pure functions, including a
deliberately contradictory feedback sequence that must not oscillate
forever), `tests/test_pager.py`, `tests/test_monologue_margin.sh` — all
against synthetic conf files, never a real overscan crop. Two things
remain untested against anything real: `main()`'s interactive loop (needs
a real STT response and a real screen to look at), and the STT-response
parser's phrasing guesses ("top right is gone," "all four are fine") —
same charitable-inference treatment as everything else in
`STT-MECHANISM.md`. Lever #1 (an actual VirtualBox resolution change)
still needs dexter access.
