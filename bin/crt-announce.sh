#!/usr/bin/env bash
# Rate-limited TV-facing announcement: speaks a short message through the TV
# audio device (distinct from the phone earpiece device) so Chris can hear a
# simple request without touching anything -- he can only respond by talking
# into the phone. Hard rate limit: at most one announcement per 15 minutes,
# enforced by a lockfile timestamp, so this can be called freely from job
# completion hooks etc. without risking a barrage.
#
# STATUS: NOT hardware-verified. CRT_TV_AUDIO_DEV is a guess (see
# AUDIO-ROUTING.md for why TV vs headset separation is likely a
# Windows-host-side problem, not solvable purely inside the VM) -- confirm
# the real device name once the VM is reachable (`aplay -L`).
#
# Usage: crt-announce.sh "the batch job needs your input"
set -euo pipefail
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

LOCK="${CRT_ANNOUNCE_LOCK:-$HOME/.crt/announce.lastrun}"
MIN_GAP="${CRT_ANNOUNCE_MIN_GAP:-900}"   # 15 minutes
TV_DEV="${CRT_TV_AUDIO_DEV:-plughw:1,0}"  # guess; verify with `aplay -L` on the VM

msg="${*:-}"
if [ -z "$msg" ]; then
  echo "usage: crt-announce.sh <message>" >&2
  exit 2
fi

mkdir -p "$(dirname "$LOCK")"
now=$(date +%s)
last=0
[ -f "$LOCK" ] && last=$(cat "$LOCK" 2>/dev/null || echo 0)
elapsed=$(( now - last ))

if [ "$elapsed" -lt "$MIN_GAP" ]; then
  wait_left=$(( MIN_GAP - elapsed ))
  echo "[crt-announce] rate-limited: last announcement ${elapsed}s ago, need ${MIN_GAP}s. Skipping (would be ready in ${wait_left}s)." >&2
  exit 1
fi

echo "$now" > "$LOCK"
exec python3 "$BIN_DIR/crt-tts.py" --device "$TV_DEV" "$msg"
