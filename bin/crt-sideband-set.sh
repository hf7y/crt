#!/usr/bin/env bash
# Sets the sideband ambient-presence state (SIDEBAND.md) other scripts
# should call at their own transition points -- not wired automatically
# anywhere yet, see SIDEBAND.md's "not done this session" note.
#
# Usage: crt-sideband-set.sh <idle|listening|thinking|speaking>
set -euo pipefail
STATE_FILE="${CRT_SIDEBAND_STATE_FILE:-$HOME/.crt/sideband.state}"

case "${1:-}" in
  idle|listening|thinking|speaking) ;;
  *)
    echo "usage: crt-sideband-set.sh <idle|listening|thinking|speaking>" >&2
    exit 2
    ;;
esac

mkdir -p "$(dirname "$STATE_FILE")"
echo "$1" > "$STATE_FILE"
