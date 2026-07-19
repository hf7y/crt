#!/usr/bin/env python3
# MIDI knob/pad -> live STT params, via the control file crt-stt-solo.py watches.
#
# Turn a knob on the Arturia MiniLab mkII and the mapped parameter updates AND a
# level bar flashes on the console screen (the engine renders it). This script is
# just the thin translator: MIDI CC/notes -> "<param> <value>" lines appended to
# CRT_CTL_FILE.
#
# STATUS: NOT runnable yet on crt-vm -- the MiniLab isn't passing through to the
# guest (see AUDIO-DEBUG / FOCUS: USB passthrough is the blocker) and mido/
# python-rtmidi aren't installed there. This is ready for when both are fixed:
#   pip install mido python-rtmidi
#   CRT_CTL_FILE=~/.crt/ctl python3 crt-midi-knobs.py --port <name>
# List ports with:  python3 crt-midi-knobs.py --list
#
# The CC numbers below are the MiniLab mkII factory defaults for the first four
# top knobs; if yours differ, either remap in Arturia MIDI Control Center or edit
# CC_MAP. Ranges MUST match crt-stt-solo.py's CTL_MAP.
import argparse, os, sys, time

# cc number -> (param, lo, hi)  -- value scaled 0..127 into [lo,hi], written in
# display units (vad %, trail/min seconds, nr 0..0.3).
CC_MAP = {
    112: ("vad",   0.3, 8.0),   # knob 1
    74:  ("nr",    0.0, 0.3),   # knob 2
    71:  ("trail", 0.3, 2.0),   # knob 3
    76:  ("min",   0.2, 1.0),   # knob 4
}
# note number -> action (pads). 'mute' toggles; others reserved.
NOTE_MAP = {
    36: "mute",   # pad 1
}

CTL = os.environ.get("CRT_CTL_FILE", os.path.expanduser("~/.crt/ctl"))


def write_ctl(line):
    os.makedirs(os.path.dirname(CTL), exist_ok=True)
    # Append; the engine reads each newly-appended line by byte offset. Knob
    # streams append fast, so truncate when large (the engine detects the size
    # drop and restarts its read offset at 0).
    mode = "w" if (os.path.exists(CTL) and os.path.getsize(CTL) > 8192) else "a"
    with open(CTL, mode) as f:
        f.write(line + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", help="MIDI input port name (substring match)")
    ap.add_argument("--list", action="store_true", help="list input ports and exit")
    args = ap.parse_args()

    try:
        import mido
    except ImportError:
        sys.exit("mido not installed. Run: pip install mido python-rtmidi")

    ports = mido.get_input_names()
    if args.list or not ports:
        print("MIDI input ports:")
        for p in ports:
            print("  ", p)
        if not ports:
            print("  (none -- is the controller passed through and powered?)")
        return

    name = next((p for p in ports if args.port and args.port in p), ports[0])
    print("[crt-midi] listening on %r -> %s" % (name, CTL))

    muted = False
    with mido.open_input(name) as inp:
        for msg in inp:
            if msg.type == "control_change" and msg.control in CC_MAP:
                param, lo, hi = CC_MAP[msg.control]
                shown = lo + (msg.value / 127.0) * (hi - lo)
                write_ctl("%s %.3f" % (param, shown))
            elif msg.type == "note_on" and msg.velocity > 0 and msg.note in NOTE_MAP:
                if NOTE_MAP[msg.note] == "mute":
                    muted = not muted
                    write_ctl("mute %d" % (1 if muted else 0))


if __name__ == "__main__":
    main()
