#!/usr/bin/env bash
# Ring the phone N times (default 4); crt-stt-solo.py (the sole mic reader)
# does the actual tone playback + pickup detection since it already owns the
# capture stream -- this just fires the request over the shared control file.
#
# STATUS: NOT hardware-verified -- unclear if the tone reads as "ringing"
# through the earpiece, or gap-voice reliably reads as "picked up" vs.
# background noise. Tune CRT_VAD_THRESHOLD/CRT_RING_ON_SECS/CRT_RING_GAP_SECS
# once tested for real.
#
# Usage: crt-ring.sh [n]
set -euo pipefail
CTL="${CRT_CTL_FILE:-$HOME/.crt/ctl}"
N="${1:-4}"
mkdir -p "$(dirname "$CTL")"
echo "ring $N" >> "$CTL"
