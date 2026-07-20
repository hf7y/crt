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

## What's built this session (offline, all testable)
- `bin/crt-calibrate-display.py`:
  - `render_pattern(width, height, margins)` — pure function, builds the
    numbered-ruler/corner-letter test pattern as a list of lines, inset by
    the given margins. Fully unit-testable (exact line count, ruler
    numbers land where expected, margin actually shrinks the drawn area).
  - `adjust_margins(margins, feedback, step=1)` — pure function, the
    hill-climb described above. Also fully unit-tested, including that it
    reports "converged" once a round changes nothing.
  - `load_display_conf` / `save_display_conf` — same simple `KEY=value`
    shape as `~/.crt/tts.conf` (existing convention from
    `crt-tts-calibrate.py`), so this fits the pattern already established
    rather than inventing a new config format.
  - A `main()` CLI loop exists but **cannot be tested this session** — it
    needs a real STT response and a real screen to look at. Treat it as a
    first draft to run live, not a verified interactive flow.
- `tests/test_calibrate_display.py` — covers the two pure functions above
  with synthetic feedback sequences (including a deliberately
  contradictory one, to confirm it doesn't oscillate forever).

## Not done this session
- Wiring the saved margin into `crt-pager.py`/`crt-monologue.sh`'s actual
  rendering (reduce effective WIDTH/HEIGHT by the margin) — the
  calibration tool produces a number, but nothing *consumes* it yet.
  Small follow-up once the calibration flow itself has been run live at
  least once (no point wiring consumption of a number nobody's confirmed
  is right).
- The STT-response-to-per-edge-feedback parser is a first-draft guess at
  phrasing ("top right is gone," "all four are fine") — real voice
  responses in a noisy room will need the same charitable-inference
  treatment as everything else in `STT-MECHANISM.md`; this hasn't been
  tuned against anything real.
- Any actual VirtualBox resolution change (lever #1 above).
