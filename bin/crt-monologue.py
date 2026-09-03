#!/usr/bin/env python3
# Ephemeral "stream of consciousness" display for the CRT. Replaces the
# plain `tail -f | fold` version: a scrolling tail can't fade/re-style
# already-printed lines, so this redraws the whole visible buffer instead.
#
#   [rest: vault:crt/header-archaeology-20260817.md]
import os, sys, time, textwrap, shutil, importlib.util

BIN_DIR = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.expanduser(os.environ.get("CRT_THOUGHT_LOG", "~/.crt/thoughts.log"))
FALLBACK_WIDTH, FALLBACK_HEIGHT = 40, 15   # CLAUDE.md's stated tube geometry
STALE_SECS = float(os.environ.get("CRT_MONO_STALE_SECS", "6"))
DROP_SECS = float(os.environ.get("CRT_MONO_DROP_SECS", "45"))
REFRESH = float(os.environ.get("CRT_MONO_REFRESH", "0.5"))

DIM_CODE = "\x1b[2m"
RESET = "\x1b[0m"


NO_MARGIN = {"top": 0, "bottom": 0, "left": 0, "right": 0}
_pager = None          # crt-pager.py, loaded once; None until first attempt


def _load_margins():
    """The overscan safe margin bin/crt-calibrate-display.py writes, read the
    way crt-pager.py reads it -- by loading crt-pager.py itself, the importlib
    pattern crt-secretary.py already uses for bin/ scripts that cannot import
    each other by name (they have hyphens in them). The module is loaded once
    and kept; the CONF FILE is re-read on every call, so a calibration run
    takes effect without restarting the window.

    Guarded, deliberately: a permanently dark window 1 is the worse failure
    mode (CLAUDE.md says so about the bridge's marker fallback, and it is just
    as true here), so anything wrong with crt-pager.py degrades to no margin
    rather than taking this process down with it."""
    global _pager
    try:
        if _pager is None:
            spec = importlib.util.spec_from_file_location(
                "crt_pager_margins", os.path.join(BIN_DIR, "crt-pager.py"))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _pager = mod
        # Path resolved per call, not from crt-pager.py's own import-time
        # global: this process outlives any one value of it, and a test that
        # cannot point the loader at its own conf file ends up asserting
        # against whatever the host machine happens to have calibrated.
        conf = os.path.expanduser(
            os.environ.get("CRT_DISPLAY_CONF", "~/.crt/display.conf"))
        return _pager.load_display_margins(conf)
    except Exception:
        return dict(NO_MARGIN)


def _env_int(name):
    """A positive integer from the environment, or 0 for unset/empty/junk."""
    try:
        v = int(os.environ.get(name, "") or 0)
    except ValueError:
        return 0
    return v if v > 0 else 0


def terminal_size():
    """Seam: tests monkeypatch this instead of the real terminal."""
    try:
        return shutil.get_terminal_size(fallback=(FALLBACK_WIDTH, FALLBACK_HEIGHT))
    except OSError:
        return os.terminal_size((FALLBACK_WIDTH, FALLBACK_HEIGHT))


def viewport(margins=None):
    """(width, height) to draw into, recomputed per frame.

    Precedence, matching crt-monologue.sh and crt-pager.py: an explicit env
    size wins, then crt-console.sh's CRT_COLS/CRT_ROWS pins, then the live
    terminal, then the tube's stated geometry. The overscan margin applies on
    top of all of them -- it describes a physical crop of the picture tube, so
    it is true no matter where the number came from."""
    size = terminal_size()
    w = _env_int("CRT_PAGER_WIDTH") or _env_int("CRT_COLS") or size.columns
    h = _env_int("CRT_MONO_HEIGHT") or _env_int("CRT_ROWS") or size.lines
    m = _load_margins() if margins is None else margins
    return (max(1, w - m.get("left", 0) - m.get("right", 0)),
            max(1, h - m.get("top", 0) - m.get("bottom", 0)))


def pad_for_margins(lines, margins):
    """Physically pushes rendered `lines` away from the tube's edges.

    viewport() only shrinks the content BOX, and render() still homes the
    cursor at the true top-left, so shrinking without indenting buys nothing:
    it pulls the right and bottom edges in twice as far as asked. What the
    tube actually showed was left=2 in display.conf and the first characters
    of every line still unreadable. Pure, so it is testable without a conf
    on disk -- the same two-step crt-book-console.py already had."""
    left = " " * max(0, margins.get("left", 0))
    padded = [left + ln for ln in lines]
    top = [""] * max(0, margins.get("top", 0))
    bottom = [""] * max(0, margins.get("bottom", 0))
    return top + padded + bottom


def render(buf, width=None, height=None, margins=None):
    # An explicit width/height is a caller (a test, mostly) stating the box
    # it wants drawn, so it gets no margin of its own unless it asks.
    if margins is None:
        margins = (dict(NO_MARGIN) if width is not None and height is not None
                   else _load_margins())
    if width is None or height is None:
        width, height = viewport(margins)
    now = time.time()
    out_lines = []
    for recv_t, text, htime in buf:
        age = now - recv_t
        wrapped = textwrap.wrap(text, width) or [""]
        if age >= STALE_SECS:
            wrapped[0] = ("%s  %s" % (htime, wrapped[0]))[:width]
            wrapped = [DIM_CODE + l.ljust(width) + RESET for l in wrapped]
        out_lines.extend(wrapped)
    view = out_lines[-height:]
    view += [""] * (height - len(view))
    sys.stdout.write("\x1b[H\x1b[2J")
    sys.stdout.write("\n".join(pad_for_margins(view, margins)))
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
                # errors="replace", not strict: this read races every
                # writer appending to thoughts.log, so it can land inside a
                # multi-byte character (a book title's accent, an em-dash
                # in a quote) that a writer's buffer split across two
                #   [rest: vault:crt/header-archaeology-20260817.md]
                with open(LOG, encoding="utf-8", errors="replace") as f:
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
