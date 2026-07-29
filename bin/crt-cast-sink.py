#!/usr/bin/env python3
# crt's half of the ecosim cast contract (ecosim/BRIEF-potato-sight-and-sound.md,
# 2026-07-29). ecosim can't write into this repo -- categorically forbidden by
# its own CLAUDE.md -- so the two projects meet at a named line protocol and
# each builds its own side. This is our side, and the whole surface is:
#
#   stdin, line-buffered, forever:   CHANNEL<TAB>TEXT
#
#     SEE   -- paint one line on the tube (stdout; point a tmux window here)
#     SAY   -- speak through the TV device, under crt-announce.sh's own
#              15-minute rate limit (NOT a second limiter -- IDLE-BAIT.md's
#              single-rate-limit rule: one clock for the TV voice, shared)
#     MARK  -- into the monologue pane, with OUR guillemet prefix (CLAUDE.md's
#              window-1 marker), which is exactly why ecosim doesn't hardcode
#              it on its side
#
# Unknown channels are ignored AND COUNTED, never dropped silently -- the
# counted part is the point. A sink that quietly eats a channel ecosim
# thinks it's sending looks identical to a sink that's working, which is the
# one-symbol-for-two-world-states failure both repos exist to complain about.
# Counters go to stderr on exit, and to stdout on `stats` (see below).
#
# The emitter promises SEE lines already fit 40 columns. We do not trust it:
# a too-wide line is truncated to the calibrated width and counted, because
# the alternative is the tube wrapping into mush and nobody knowing why.
#
# Usage:
#   ecosim-cast.py --cast | ssh potato 'crt-cast-sink.py'
#   crt-cast-sink.py --dry-run      # echo what WOULD be said/marked
import os
import sys
import subprocess
import importlib.util

BIN_DIR = os.path.dirname(os.path.abspath(__file__))
CHANNELS = ("SEE", "SAY", "MARK")


def _load_pager():
    """Width/overscan logic is crt-pager.py's, imported rather than retyped
    (build discipline: config read from ONE source). Hyphenated filename, so
    it can't be a plain import."""
    path = os.path.join(BIN_DIR, "crt-pager.py")
    spec = importlib.util.spec_from_file_location("crt_pager", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def display_width():
    """Same number crt-monologue.sh and crt-pager.py paint to: env override >
    real terminal > 40, minus the calibrated overscan margins."""
    pager = _load_pager()
    width, height = pager.detect_size()
    width, _ = pager.apply_margins(width, height, pager.load_display_margins())
    return width


class Sink:
    def __init__(self, width, dry_run=False, out=None, err=None):
        self.width = width
        self.dry_run = dry_run
        self.out = out if out is not None else sys.stdout
        self.err = err if err is not None else sys.stderr
        self.counts = {c: 0 for c in CHANNELS}
        self.counts.update({"UNKNOWN": 0, "MALFORMED": 0, "TRUNCATED": 0,
                            "SAY_DROPPED": 0})

    # -- channels ---------------------------------------------------------

    def see(self, text):
        if len(text) > self.width:
            text = text[:self.width]
            self.counts["TRUNCATED"] += 1
        print(text, file=self.out, flush=True)

    def say(self, text):
        if self.dry_run:
            print("[dry-run SAY] " + text, file=self.err, flush=True)
            return
        # crt-announce.sh exits non-zero when rate-limited OR when the TV
        # device didn't actually make a sound. Both mean "nobody heard it",
        # which is exactly what the emitter was told to assume can happen --
        # so it's counted, not raised.
        rc = subprocess.call([os.path.join(BIN_DIR, "crt-announce.sh"), text],
                             stdout=subprocess.DEVNULL)
        if rc != 0:
            self.counts["SAY_DROPPED"] += 1

    def mark(self, text):
        if self.dry_run:
            print("[dry-run MARK] " + text, file=self.err, flush=True)
            return
        subprocess.call([os.path.join(BIN_DIR, "crt-think.sh"), "» " + text],
                        stdout=subprocess.DEVNULL)

    # -- protocol ---------------------------------------------------------

    def feed(self, line):
        line = line.rstrip("\n")
        if not line.strip():
            return
        if "\t" not in line:
            self.counts["MALFORMED"] += 1
            print("[cast] malformed (no tab): %.40s" % line, file=self.err,
                  flush=True)
            return
        channel, text = line.split("\t", 1)
        channel = channel.strip().upper()
        if channel not in CHANNELS:
            self.counts["UNKNOWN"] += 1
            print("[cast] unknown channel %r" % channel, file=self.err,
                  flush=True)
            return
        self.counts[channel] += 1
        {"SEE": self.see, "SAY": self.say, "MARK": self.mark}[channel](text)

    def run(self, stream):
        for line in stream:
            self.feed(line)
        return self.counts

    def report(self):
        parts = ["%s=%d" % (k, v) for k, v in sorted(self.counts.items()) if v]
        return "[cast] " + (" ".join(parts) if parts else "nothing received")


def main(argv):
    dry_run = "--dry-run" in argv
    sink = Sink(display_width(), dry_run=dry_run)
    try:
        sink.run(sys.stdin)
    except KeyboardInterrupt:
        pass
    finally:
        # Always, on every exit path: a silent sink and a working one must
        # not look the same from the far end.
        print(sink.report(), file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
