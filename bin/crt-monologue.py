#!/usr/bin/env python3
# Ephemeral "stream of consciousness" display for the CRT. Replaces the
# plain `tail -f | fold` version: a scrolling tail can't fade/re-style
# already-printed lines, so this redraws the whole visible buffer instead.
#
# Look: fresh lines show with NO timestamp (bare text, feels like a live
# stream of thought). Once a line goes stale (STALE_SECS old), it gains a
# hex timestamp prefix and dims -- the timestamp is a "this is old" signal,
# not a routine label. Lines older than DROP_SECS are dropped entirely
# (ephemeral, not a permanent transcript -- that's what thoughts.log/stt.log
# on disk are for).
#
# STATUS: written 2026-07-19, not yet hardware-verified for how dim/bold
# ANSI actually reads on the real CRT phosphor -- tune DIM_CODE if it's
# unreadable.
import os, sys, time, textwrap, shutil

LOG = os.path.expanduser(os.environ.get("CRT_THOUGHT_LOG", "~/.crt/thoughts.log"))
WIDTH = int(os.environ.get("CRT_PAGER_WIDTH", "40"))
# Auto-detect the real pane size by default -- a hardcoded height taller than
# the actual pane causes real terminal scroll, clipping the top of the
# redraw (bit us once: pane was 11 rows, default height was 12).
_term_h = shutil.get_terminal_size(fallback=(40, 11)).lines
HEIGHT = int(os.environ.get("CRT_MONO_HEIGHT", str(_term_h)))
STALE_SECS = float(os.environ.get("CRT_MONO_STALE_SECS", "6"))
DROP_SECS = float(os.environ.get("CRT_MONO_DROP_SECS", "45"))
REFRESH = float(os.environ.get("CRT_MONO_REFRESH", "0.5"))

DIM_CODE = "\x1b[2m"
RESET = "\x1b[0m"


def render(buf):
    now = time.time()
    out_lines = []
    for recv_t, text, htime in buf:
        age = now - recv_t
        wrapped = textwrap.wrap(text, WIDTH) or [""]
        if age >= STALE_SECS:
            wrapped[0] = ("%s  %s" % (htime, wrapped[0]))[:WIDTH]
            wrapped = [DIM_CODE + l.ljust(WIDTH) + RESET for l in wrapped]
        out_lines.extend(wrapped)
    view = out_lines[-HEIGHT:]
    view += [""] * (HEIGHT - len(view))
    sys.stdout.write("\x1b[H\x1b[2J")
    sys.stdout.write("\n".join(view))
    sys.stdout.flush()


def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    open(LOG, "a").close()
    pos = os.path.getsize(LOG)
    buf = []   # list of (recv_time, text, hex_timestamp_str)
    last_draw = 0.0
    while True:
        try:
            sz = os.path.getsize(LOG)
            if sz < pos:
                pos = 0
            if sz > pos:
                with open(LOG) as f:
                    f.seek(pos)
                    chunk = f.read()
                    pos = f.tell()
                for ln in chunk.splitlines():
                    if not ln.strip():
                        continue
                    htime, text = (ln.split("  ", 1) + [""])[:2] \
                        if "  " in ln else ("", ln)
                    buf.append((time.time(), text or ln, htime))
        except OSError:
            pass
        now = time.time()
        buf = [b for b in buf if now - b[0] < DROP_SECS]
        if now - last_draw >= REFRESH:
            render(buf)
            last_draw = now
        time.sleep(0.1)


if __name__ == "__main__":
    main()
