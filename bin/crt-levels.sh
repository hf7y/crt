#!/usr/bin/env bash
# Live microphone level meter for the crt console.
#
# Holds ONE continuous arecord on the shared ALSA capture ('crtmic', the dsnoop
# device from systemd/asound.conf) and pipes raw PCM to crt-meter.py. Two
# continuous arecord readers coexist on dsnoop fine (the meter + stt-feed); the
# failure modes we hit were (1) a stale/stuck arecord holding dsnoop in a bad
# state, and (2) feeding the python script in via a `python3 -` heredoc, which
# stole stdin from the audio pipe. Keeping one stream open also keeps
# VirtualBox's emulated capture warm.
#
# Draws a bar with the VAD trigger threshold marked ('|') so you can see whether
# your voice reaches the mic and crosses the gate stt-feed needs:
#
#   MIC [####|............]  12.4% TALK
#
# Run standalone anytime to check mic health; crt-console.sh also shows it in a
# strip at the bottom of the screen.
set -uo pipefail

BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEV="${CRT_METER_DEV:-crtmic}"
export CRT_VAD_THRESHOLD="${CRT_VAD_THRESHOLD:-1.5}"
export CRT_METER_WIDTH="${CRT_METER_WIDTH:-20}"
export CRT_METER_FULL="${CRT_METER_FULL:-0.30}"

while true; do
  arecord -D "$DEV" -f S16_LE -c1 -r16000 -t raw 2>/dev/null \
    | python3 "$BIN_DIR/crt-meter.py"
  # arecord or python exited (device hiccup); pause briefly and reopen.
  sleep 0.3
done
