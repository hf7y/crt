#!/usr/bin/env python3
# Simple looping ASCII art screensaver for the CRT, 40x15.
import sys, time, itertools

FRAMES = [
r"""
        .-.
       (o.o)
        |=|
       __|__
     //.=|=.\\
    // .=|=. \\
        |
      _/ \_
     LISTENING...
""",
r"""
        .-.
       (-.-)
        |=|
       __|__
     //.=|=.\\
    // .=|=. \\
        |
      _/ \_
     ...zzz...
""",
]

def main():
    for frame in itertools.cycle(FRAMES):
        sys.stdout.write("\x1b[H\x1b[2J")
        sys.stdout.write(frame)
        sys.stdout.flush()
        time.sleep(2)

if __name__ == "__main__":
    main()
