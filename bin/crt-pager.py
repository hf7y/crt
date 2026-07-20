#!/usr/bin/env python3
# Slow-scrolling pager for long text on the CRT.
#
# VISION (per 2026-07-19 direction): the printer is the channel for long-form
# output (job reports, logs) -- the CRT stays terse. But when longer text DOES
# need to show on the CRT (a paragraph reply, a long status), it should scroll
# slowly line-by-line rather than dumping/wrapping unreadably, and be
# controllable: a MIDI knob jogs the scroll position, or voice commands
# (next/back/pause/resume) step it, arriving via the same CRT_CTL_FILE
# mechanism already used for STT live-tuning (bin/crt-stt-solo.py) -- one
# control channel, multiple consumers.
#
# STATUS: NOT hardware-verified (written without a live CRT to check layout
# against). Terminal-based (curses-free, plain ANSI) so it works over the
# existing tmux pane.
#
# WIDTH/HEIGHT (2026-07-19, was hardcoded 40x14): CRT_PAGER_WIDTH/HEIGHT env
# vars win if set; otherwise auto-detect the real terminal size
# (shutil.get_terminal_size) so this renders correctly whether it's the
# actual small CRT tmux pane, a resized VM window, or a dev machine's
# terminal during testing -- a hardcoded assumption silently misrenders the
# moment any of those differ. Only falls back to the CLAUDE.md 40x15 CRT
# default when detection itself fails (e.g. no tty at all, like a cron job).
#
# Usage:
#   crt-pager.py file.txt
#   some_command | crt-pager.py
#   CRT_CTL_FILE=~/.crt/ctl crt-pager.py notes.txt   # knob/voice control
#
# Control file lines this reads (in addition to whatever crt-stt-solo.py's
# CTL_MAP already uses -- these are namespaced with "page " so the two
# scripts can share one file without colliding):
#   page next   / page back    -- jump one screen-height
#   page pause  / page resume  -- stop/start auto-scroll
#   page scroll <n>            -- jog by n lines (+forward/-back), e.g. from
#                                  a MIDI knob's relative/delta mode
import sys, os, time, shutil, textwrap

FALLBACK_WIDTH = 40   # CLAUDE.md's assumed CRT geometry -- last resort only
FALLBACK_HEIGHT = 15


def detect_size():
    """env override > real terminal size > CRT hardware fallback. Kept as a
    standalone function (not inlined at import time) so tests can call it
    directly with a monkeypatched shutil.get_terminal_size."""
    env_w = os.environ.get("CRT_PAGER_WIDTH")
    env_h = os.environ.get("CRT_PAGER_HEIGHT")
    if env_w and env_h:
        return int(env_w), int(env_h)
    try:
        cols, lines = shutil.get_terminal_size(fallback=(FALLBACK_WIDTH, FALLBACK_HEIGHT))
    except OSError:
        cols, lines = FALLBACK_WIDTH, FALLBACK_HEIGHT
    return int(env_w) if env_w else cols, int(env_h) if env_h else max(2, lines - 1)


WIDTH, HEIGHT = detect_size()   # HEIGHT already leaves 1 line for the footer
SCROLL_SECS = float(os.environ.get("CRT_PAGER_SCROLL_SECS", "2.5"))  # per line
CTL = os.environ.get("CRT_CTL_FILE", "")


def load_text():
    if len(sys.argv) > 1:
        return open(sys.argv[1]).read()
    return sys.stdin.read()


def wrap_lines(text):
    lines = []
    for para in text.splitlines():
        if not para.strip():
            lines.append("")
            continue
        lines.extend(textwrap.wrap(para, WIDTH) or [""])
    return lines


def render(lines, top):
    view = lines[top:top + HEIGHT]
    view += [""] * (HEIGHT - len(view))
    sys.stdout.write("\x1b[H\x1b[2J")   # home + clear
    sys.stdout.write("\n".join(l.ljust(WIDTH) for l in view))
    more = "MORE (knob/next)" if top + HEIGHT < len(lines) else "END"
    pct = int(100 * min(1.0, (top + HEIGHT) / max(1, len(lines))))
    sys.stdout.write("\n%-3d%% %s" % (pct, more))
    sys.stdout.flush()


def main():
    lines = wrap_lines(load_text())
    top = 0
    paused = False
    ctl_pos = 0
    last_scroll = time.time()
    render(lines, top)
    try:
        while True:
            now = time.time()
            if CTL:
                try:
                    sz = os.path.getsize(CTL)
                    if sz < ctl_pos:
                        ctl_pos = 0
                    if sz > ctl_pos:
                        with open(CTL) as fh:
                            fh.seek(ctl_pos)
                            chunk = fh.read()
                            ctl_pos = fh.tell()
                        for ln in chunk.splitlines():
                            if not ln.startswith("page "):
                                continue
                            cmd = ln[len("page "):].strip()
                            if cmd == "next":
                                top = min(max(0, len(lines) - HEIGHT), top + HEIGHT)
                            elif cmd == "back":
                                top = max(0, top - HEIGHT)
                            elif cmd == "pause":
                                paused = True
                            elif cmd == "resume":
                                paused = False
                            elif cmd.startswith("scroll"):
                                try:
                                    delta = int(cmd.split()[1])
                                    top = max(0, min(max(0, len(lines) - HEIGHT), top + delta))
                                except (IndexError, ValueError):
                                    pass
                            render(lines, top)
                except OSError:
                    pass
            if not paused and now - last_scroll >= SCROLL_SECS:
                if top < len(lines) - HEIGHT:
                    top += 1
                    render(lines, top)
                last_scroll = now
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
