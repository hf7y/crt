#!/usr/bin/env bash
# Ring the phone N times (default 4); crt-stt-solo.py (the sole mic reader)
# does the actual tone playback + pickup detection since it already owns the
# capture stream -- this just fires the request over the shared control file.
#
#   [rest: vault:crt/header-archaeology-20260817.md]
set -euo pipefail
CTL="${CRT_CTL_FILE:-$HOME/.crt/ctl}"
N="${1:-4}"
mkdir -p "$(dirname "$CTL")"
echo "ring $N" >> "$CTL"
