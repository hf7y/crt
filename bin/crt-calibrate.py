#!/usr/bin/env python3
"""Interactive CRT display calibration, driven over SSH.

Run this over ssh (any workstation) while sitting in front of the physical
CRT. It writes its test pattern directly to /dev/tty1 -- the real console --
not to the ssh session's own pty, so the picture you're judging is the one
actually on the tube, decoupled from wherever your keyboard input is coming
from.

Defaults below are hardcoded from what Zach already knows about this
specific setup (2026-07-22), not guessed from scratch each run:
  - This tube OVERSCANS: start margins non-zero. A margin of 0 will clip.
  - The default resolution/font is hard to read: start at a LARGE font,
    not the smallest. Bigger is the safe starting error.
  - Primary RGB (red/green/blue) render badly on this analog tube (chroma
    bleed/ringing over composite-into-RF -- see CLAUDE.md's ANSI 31/32/34/
    91/92/94 ban). Palette is hard-restricted to yellow/magenta/cyan/white.
    Don't add red/green/blue back in without re-confirming on the real
    tube; this isn't a stylistic choice, it's a hardware limitation.

Config persists to ~/.crt/calibrate.conf (same KEY=value shape as the
existing ~/.crt/display.conf / ~/.crt/tts.conf convention in this repo).
"""
import os
import sys
import termios
import tty
import subprocess

TTY_DEVICE = "/dev/tty1"
CONF_PATH = os.path.expanduser("~/.crt/calibrate.conf")

# CRT-safe palette only -- see CLAUDE.md. tmux/ANSI colour indices, not
# raw 30-37 codes, since we write raw ANSI SGR directly to /dev/tty1.
SAFE_COLORS = [
    ("yellow", "33"),
    ("magenta", "35"),
    ("cyan", "36"),
    ("white", "37"),
]

# Terminus ladder actually installed on this box (checked live 2026-07-22),
# smallest to largest. Start large: default resolution reads as too small.
FONT_LADDER = [
    "Lat15-Terminus12x6",
    "Lat15-Terminus14",
    "Lat15-Terminus16",
    "Lat15-Terminus18x10",
    "Lat15-Terminus20x10",
    "Lat15-Terminus22x11",
    "Lat15-Terminus24x12",
    "Lat15-Terminus28x14",
    "Lat15-Terminus32x16",
]
DEFAULT_FONT_INDEX = len(FONT_LADDER) - 1  # 32x16, the biggest

DEFAULTS = {
    "margin_top": 2,
    "margin_bottom": 2,
    "margin_left": 3,
    "margin_right": 3,
    "bezel": 2,       # corner cutout radius, in character cells
    "color_index": 0,  # yellow
    "font_index": DEFAULT_FONT_INDEX,
}

SIDE_KEYS = {
    "1": "margin_top",
    "2": "margin_bottom",
    "3": "margin_left",
    "4": "margin_right",
}


def load_conf():
    state = dict(DEFAULTS)
    if not os.path.exists(CONF_PATH):
        return state
    with open(CONF_PATH) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k in state:
                state[k] = int(v) if v.lstrip("-").isdigit() else v
    return state


def save_conf(state):
    os.makedirs(os.path.dirname(CONF_PATH), exist_ok=True)
    with open(CONF_PATH, "w") as f:
        f.write("# written by crt-calibrate.py\n")
        for k, v in state.items():
            f.write(f"{k}={v}\n")


def term_size(tty_path):
    # Ask the kernel for the real size of the physical console, not our
    # own ssh pty -- they can differ (that's the whole point of this tool).
    out = subprocess.run(
        ["stty", "size"], stdin=open(tty_path), capture_output=True, text=True
    )
    rows, cols = out.stdout.split()
    return int(rows), int(cols)


def auto_safe_area(rows, cols, margin=1):
    """Zero-config safe-print-area guess for a window that's never been
    through the interactive dial-in above: inset every edge by `margin`
    cell (one column left, one right, one row top, one row bottom for the
    default margin=1), matching CLAUDE.md's "this setup overscans, don't
    default margins to 0" rule with the smallest reasonable non-zero
    guess. Not a replacement for render_pattern's bezel-aware calibration
    -- just a sane starting point for a window size nobody's calibrated
    yet, e.g. a dev tmux pane far from the real CRT."""
    return max(1, rows - 2 * margin), max(1, cols - 2 * margin)


def render_pattern(rows, cols, state):
    top, bottom = state["margin_top"], state["margin_bottom"]
    left, right = state["margin_left"], state["margin_right"]
    bezel = state["bezel"]
    color_name, color_code = SAFE_COLORS[state["color_index"] % len(SAFE_COLORS)]
    font = FONT_LADDER[state["font_index"] % len(FONT_LADDER)]

    inner_w = max(cols - left - right, 4)
    inner_h = max(rows - top - bottom, 4)

    lines = [""] * rows

    def blank_row():
        return [" "] * cols

    grid = [blank_row() for _ in range(rows)]

    def in_bezel_corner(r, c):
        # r, c are 0-indexed within the inset safe area
        corners = [(0, 0), (0, inner_w - 1), (inner_h - 1, 0), (inner_h - 1, inner_w - 1)]
        for cr, cc in corners:
            if abs(r - cr) + abs(c - cc) < bezel:
                return True
        return False

    # Corner letters + ruler ticks, inside the safe area, skipping the
    # simulated rounded-bezel cutout at each corner.
    for r in range(inner_h):
        for c in range(inner_w):
            ch = " "
            if r == 0 and c == 0:
                ch = "A"
            elif r == 0 and c == inner_w - 1:
                ch = "B"
            elif r == inner_h - 1 and c == 0:
                ch = "C"
            elif r == inner_h - 1 and c == inner_w - 1:
                ch = "D"
            elif r == 0 or r == inner_h - 1:
                ch = str(c % 10)
            elif c == 0 or c == inner_w - 1:
                ch = str(r % 10)
            if in_bezel_corner(r, c):
                ch = " "
            gr, gc = r + top, c + left
            if 0 <= gr < rows and 0 <= gc < cols:
                grid[gr][gc] = ch

    for r in range(rows):
        lines[r] = "".join(grid[r])

    banner = f" margins T{top} B{bottom} L{left} R{right}  bezel {bezel}  {color_name}  {font} "
    if len(banner) < cols:
        mid = rows // 2
        pad = (cols - len(banner)) // 2
        lines[mid] = (" " * pad + banner)[:cols].ljust(cols)

    body = f"\x1b[{color_code}m" + "\r\n".join(lines) + "\x1b[0m"
    return body


def write_screen(tty_fd, rows, cols, state):
    os.write(tty_fd, b"\x1b[2J\x1b[H")  # clear + home
    os.write(tty_fd, render_pattern(rows, cols, state).encode())


def apply_font(state):
    font = FONT_LADDER[state["font_index"] % len(FONT_LADDER)]
    path = f"/usr/share/consolefonts/{font}.psf.gz"
    subprocess.run(["sudo", "setfont", path, "-C", TTY_DEVICE])


HELP = """\
crt-calibrate.py -- keys:
  1/2/3/4  select margin: top/bottom/left/right
  + / -    grow / shrink the selected margin
  [ / ]    shrink / grow the corner bezel cutout
  c        cycle safe color (yellow -> magenta -> cyan -> white)
  f / F    smaller / larger console font (applies live, needs sudo once)
  s        save to ~/.crt/calibrate.conf
  q        quit (prompts to save if unsaved changes)
"""


def main():
    if not sys.stdin.isatty():
        print("run this from an interactive ssh session (needs a real stdin tty)")
        sys.exit(1)

    print(HELP)
    input("Press Enter once you're looking at the CRT itself (not this ssh window)...")

    subprocess.run(["sudo", "-v"])  # cache sudo once, up front, for font changes

    state = load_conf()
    selected = "margin_top"
    dirty = False

    tty_fd = os.open(TTY_DEVICE, os.O_WRONLY)
    rows, cols = term_size(TTY_DEVICE)

    apply_font(state)
    write_screen(tty_fd, rows, cols, state)

    stdin_fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(stdin_fd)
    try:
        tty.setraw(stdin_fd)
        while True:
            ch = sys.stdin.read(1)
            if ch == "q":
                if dirty:
                    termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old_settings)
                    resp = input("unsaved changes -- save before quitting? [y/N] ")
                    if resp.lower().startswith("y"):
                        save_conf(state)
                    tty.setraw(stdin_fd)
                break
            elif ch in SIDE_KEYS:
                selected = SIDE_KEYS[ch]
            elif ch == "+":
                state[selected] += 1
                dirty = True
            elif ch == "-":
                state[selected] = max(0, state[selected] - 1)
                dirty = True
            elif ch == "[":
                state["bezel"] = max(0, state["bezel"] - 1)
                dirty = True
            elif ch == "]":
                state["bezel"] += 1
                dirty = True
            elif ch == "c":
                state["color_index"] = (state["color_index"] + 1) % len(SAFE_COLORS)
                dirty = True
            elif ch == "f":
                state["font_index"] = max(0, state["font_index"] - 1)
                apply_font(state)
                rows, cols = term_size(TTY_DEVICE)
                dirty = True
            elif ch == "F":
                state["font_index"] = min(len(FONT_LADDER) - 1, state["font_index"] + 1)
                apply_font(state)
                rows, cols = term_size(TTY_DEVICE)
                dirty = True
            elif ch == "s":
                save_conf(state)
                dirty = False
            write_screen(tty_fd, rows, cols, state)
    finally:
        termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old_settings)
        os.close(tty_fd)


if __name__ == "__main__":
    main()
