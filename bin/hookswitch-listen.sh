#!/usr/bin/env bash
# Listens for the hookswitch signal and pauses/resumes stt-feed.sh.
#
# Hardware: the printed hook (cad/hook_lever.scad) presses a mini
# microswitch mounted in cad/switch_mount.scad. That switch is wired to a
# cheap USB arcade-button/keyboard-encoder board (NOT a relay — this is a
# logic-level signal, not a load worth switching), configured to send one
# key when closed. Set CRT_HOOK_KEY below to that key's name from `evtest`.
#
# Convention: handset ON the hook (switch closed, key held) -> session
# paused. Handset OFF the hook (lifted) -> session resumes listening.
set -euo pipefail

HOOK_KEY="${CRT_HOOK_KEY:-KEY_F13}"
DEVICE="${CRT_HOOK_DEVICE:-}"   # e.g. /dev/input/by-id/usb-...-event-kbd

if [ -z "$DEVICE" ]; then
  echo "[hookswitch] set CRT_HOOK_DEVICE to the encoder's /dev/input event node." >&2
  echo "[hookswitch] find it with: evtest  (or ls /dev/input/by-id/)" >&2
  exit 1
fi

echo "[hookswitch] watching $DEVICE for $HOOK_KEY"

evtest "$DEVICE" 2>/dev/null | while read -r line; do
  case "$line" in
    *"$HOOK_KEY"*"value 1"*)
      echo "[hookswitch] on-hook -> pausing STT"
      pkill -STOP -f stt-feed.sh 2>/dev/null || true
      ;;
    *"$HOOK_KEY"*"value 0"*)
      echo "[hookswitch] off-hook -> resuming STT"
      pkill -CONT -f stt-feed.sh 2>/dev/null || true
      ;;
  esac
done
