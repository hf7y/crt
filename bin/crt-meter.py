#!/usr/bin/env python3
# Reads raw S16_LE mono 16 kHz PCM on stdin (piped from `arecord`) and draws a
# live single-line level meter with the VAD threshold marked. Kept in its own
# file (not a `python3 -` heredoc) so stdin stays free for the audio stream.
import sys, os, array

RATE = 16000
CHUNK = int(RATE * 0.1)              # 100 ms per redraw
NBYTES = CHUNK * 2
thresh = float(os.environ.get('CRT_VAD_THRESHOLD', '1.5')) / 100.0
width = int(os.environ.get('CRT_METER_WIDTH', '20'))
full = float(os.environ.get('CRT_METER_FULL', '0.30'))
thr_col = max(0, min(width - 1, int(thresh / full * width)))

while True:
    data = sys.stdin.buffer.read(NBYTES)
    if not data:
        break
    if len(data) % 2:
        data = data[:-1]
    a = array.array('h')
    a.frombytes(data)
    if not a:
        continue
    peak = max(abs(x) for x in a) / 32768.0
    filled = max(0, min(width, int(peak / full * width)))
    bar = ''.join('#' if i < filled else ('|' if i == thr_col else '.')
                  for i in range(width))
    tag = 'TALK' if filled > thr_col else '    '
    sys.stdout.write('\rMIC [%s] %5.1f%% %s' % (bar, peak * 100, tag))
    sys.stdout.flush()
