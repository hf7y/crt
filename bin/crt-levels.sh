#!/usr/bin/env bash
# Live microphone level meter for the crt console.
#
# Holds ONE continuous arecord on the shared ALSA capture ('crtmic', the dsnoop
# device from systemd/asound.conf) and pipes raw PCM to crt-meter.py -- see
# that script's own header for why it's a real file, not a `python3 -`
# heredoc (stdin theft). A second concurrent reader (this + stt-feed) is
# fine on dsnoop; a stale/stuck arecord holding it in a bad state was not.
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
