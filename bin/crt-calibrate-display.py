#!/usr/bin/env python3
# The overscan calibration game -- see DISPLAY-CALIBRATION.md for the full
# design. Renders a numbered-ruler/corner-letter test pattern inset by a
# safe-margin guess, asks (by voice, in real use) which edges are cut off,
# and hill-climbs the margin until it converges.
#
# STATUS: NOT hardware-verified. render_pattern() and adjust_margins() are
# pure functions covered by tests/test_calibrate_display.py. main()'s
# interactive loop has never run against a real screen/STT -- treat it as
# a first draft, not a verified flow (see DISPLAY-CALIBRATION.md).
#
# Usage:
#   crt-calibrate-display.py show                 # render current margins once
#   crt-calibrate-display.py run                   # interactive calibration loop
import json
import os
import sys

DISPLAY_CONF = os.path.expanduser(os.environ.get("CRT_DISPLAY_CONF", "~/.crt/display.conf"))
DEFAULT_MARGINS = {"top": 1, "bottom": 1, "left": 2, "right": 2}
EDGES = ("top", "bottom", "left", "right")


def render_pattern(width, height, margins):
    """Numbered-ruler/corner-letter test pattern, inset by margins (a dict
    with top/bottom/left/right in character cells). Pure -- no I/O."""
    top = max(0, margins.get("top", 0))
    bottom = max(0, margins.get("bottom", 0))
    left = max(0, margins.get("left", 0))
    right = max(0, margins.get("right", 0))
    inner_w = max(1, width - left - right)
    inner_h = max(1, height - top - bottom)

    canvas = [[" "] * width for _ in range(height)]

    # Rulers first, corners drawn last so they always win the shared cell
    # at each corner (a ruler digit and a corner letter both want (top,left)
    # etc. -- the corner label is the more important signal to preserve).
    for row in (top, top + inner_h - 1):
        if 0 <= row < height:
            for i in range(0, inner_w, 5):
                col = left + i
                if 0 <= col < width:
                    canvas[row][col] = str((i // 5) % 10)

    for col in (left, left + inner_w - 1):
        if 0 <= col < width:
            for i in range(0, inner_h, 3):
                row = top + i
                if 0 <= row < height:
                    canvas[row][col] = str((i // 3) % 10)

    corners = {
        (top, left): "A",
        (top, left + inner_w - 1): "B",
        (top + inner_h - 1, left): "C",
        (top + inner_h - 1, left + inner_w - 1): "D",
    }
    for (r, c), ch in corners.items():
        if 0 <= r < height and 0 <= c < width:
            canvas[r][c] = ch

    return ["".join(r) for r in canvas]


def adjust_margins(margins, feedback, step=1, min_margin=0):
    """feedback: {edge: True-if-cut-off}. Grows margin on cut-off edges,
    shrinks (reclaims) margin on confirmed-fine edges. Returns
    (new_margins, converged) -- converged is True once a round changes
    nothing, i.e. every cut-off edge already has margin and every fine
    edge is already at min_margin."""
    new = dict(margins)
    changed = False
    for edge in EDGES:
        cut_off = feedback.get(edge)
        if cut_off is None:
            continue
        current = margins.get(edge, 0)
        if cut_off:
            new[edge] = current + step
            changed = True
        elif current > min_margin:
            new[edge] = max(min_margin, current - step)
            changed = True
    return new, (not changed)


def parse_feedback(text):
    """Best-effort: turn a spoken-shaped response into per-edge cut-off
    flags. UNTESTED against real STT output -- see DISPLAY-CALIBRATION.md's
    "not done this session" note. 'all four are fine'/'looks good' clears
    every edge; otherwise looks for edge names near negative words."""
    low = text.lower()
    if any(p in low for p in ("all four", "looks good", "all fine", "nothing cut off", "perfect")):
        return {e: False for e in EDGES}
    feedback = {}
    cut_words = ("cut off", "cut", "gone", "missing", "can't see", "cant see")
    for edge in EDGES:
        names = {"top": ("top",), "bottom": ("bottom",),
                  "left": ("left",), "right": ("right",)}[edge]
        for name in names:
            if name in low:
                # crude proximity check: any cut-word anywhere in the
                # response counts against every edge mentioned by name.
                feedback[edge] = any(w in low for w in cut_words)
    return feedback


def load_display_conf(path=DISPLAY_CONF):
    margins = dict(DEFAULT_MARGINS)
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                if k in EDGES:
                    try:
                        margins[k] = int(v.strip())
                    except ValueError:
                        pass
    return margins


def save_display_conf(margins, path=DISPLAY_CONF):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w") as f:
        for edge in EDGES:
            f.write("%s=%d\n" % (edge, margins.get(edge, 0)))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    margins = load_display_conf()
    width, height = 40, 15  # CLAUDE.md's assumed CRT geometry

    if cmd == "show":
        for line in render_pattern(width, height, margins):
            print(line)
        return

    if cmd == "run":
        round_n = 0
        while True:
            round_n += 1
            sys.stderr.write("[calibrate] round %d, margins=%s\n" % (round_n, margins))
            for line in render_pattern(width, height, margins):
                print(line)
            sys.stderr.write(
                "Can you see the letter in every corner? Which edges are cut off? "
                "(or say 'looks good')\n> ")
            try:
                response = input()
            except EOFError:
                break
            feedback = parse_feedback(response)
            margins, converged = adjust_margins(margins, feedback)
            if converged:
                sys.stderr.write("[calibrate] converged: %s\n" % margins)
                break
        save_display_conf(margins)
        sys.stderr.write("[calibrate] saved to %s\n" % DISPLAY_CONF)
        return

    sys.stderr.write("usage: crt-calibrate-display.py <show|run>\n")
    sys.exit(2)


if __name__ == "__main__":
    main()
