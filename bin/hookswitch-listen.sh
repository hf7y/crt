#!/usr/bin/env bash
# Listens for the hookswitch signal and pauses/resumes stt-feed.sh.
# See HOOKSWITCH.md for the full behavior spec.
#
# Hardware: the printed hook (cad/hook_lever.scad) presses a mini
# microswitch mounted in cad/switch_mount.scad. That switch is wired to a
# cheap USB arcade-button/keyboard-encoder board (NOT a relay — this is a
# logic-level signal, not a load worth switching), configured to send one
# key when closed. Set CRT_HOOK_KEY below to that key's name from `evtest`.
#
# Convention: handset ON the hook (switch closed, key held) -> session
# paused. Handset OFF the hook (lifted) -> session resumes listening.
#
# DEBOUNCE (2026-07-19, HOOKSWITCH.md): a mechanical switch chatters for a
# few ms around each real transition. Un-debounced, that chatter fires a
# real STOP/CONT at stt-feed.sh per bounce, and a reordered STOP-after-CONT
# can leave STT silently stopped while the handset is genuinely off-hook.
# Fix: only commit a state change once the raw signal has held steady
# (no new bounce) for a full CRT_HOOK_DEBOUNCE_MS window -- trailing-edge
# debounce via `read -t`'s timeout as the "has it gone quiet" signal.
set -uo pipefail

HOOK_KEY="${CRT_HOOK_KEY:-KEY_F13}"
DEVICE="${CRT_HOOK_DEVICE:-}"   # e.g. /dev/input/by-id/usb-...-event-kbd
DEBOUNCE_MS="${CRT_HOOK_DEBOUNCE_MS:-50}"
DEBOUNCE_S=$(awk -v ms="$DEBOUNCE_MS" 'BEGIN{printf "%.3f", ms/1000}')

apply_state() {
  case "$1" in
    on)
      echo "[hookswitch] on-hook -> pausing STT"
      pkill -STOP -f stt-feed.sh 2>/dev/null || true
      ;;
    off)
      echo "[hookswitch] off-hook -> resuming STT"
      pkill -CONT -f stt-feed.sh 2>/dev/null || true
      ;;
  esac
}

# Extracted so tests/test_hookswitch_debounce.sh can feed synthetic raw
# events through the exact same state machine without a real evtest stream.
# `read -t`'s exit status distinguishes a genuine timeout (>128, the
# quiet-period signal we debounce on) from EOF/error (anything else --
# evtest died or the device disconnected, not a thing to loop forever on).
debounce_loop() {
  local committed="" pending="" rc
  while true; do
    if IFS= read -r -t "$DEBOUNCE_S" line; then
      case "$line" in
        *"$HOOK_KEY"*"value 1"*) pending="on" ;;
        *"$HOOK_KEY"*"value 0"*) pending="off" ;;
        *) ;;
      esac
      continue   # new raw event -- restart the quiet-period wait
    else
      rc=$?
    fi
    if [ "$rc" -gt 128 ]; then
      # timed out: no new raw event for a full debounce window, so
      # whatever's pending has settled. Commit it once, if it's a real change.
      if [ -n "$pending" ] && [ "$pending" != "$committed" ]; then
        apply_state "$pending"
        committed="$pending"
      fi
      pending=""
    else
      echo "[hookswitch] input ended, exiting" >&2
      return 1
    fi
  done
}

# Guarded so tests/test_hookswitch_debounce.sh can `source` this file (to
# reuse apply_state/debounce_loop against synthetic input) without also
# triggering the real device requirement/evtest launch below.
if [ "${CRT_HOOK_TEST_MODE:-0}" = "0" ]; then
  if [ -z "$DEVICE" ]; then
    echo "[hookswitch] set CRT_HOOK_DEVICE to the encoder's /dev/input event node." >&2
    echo "[hookswitch] find it with: evtest  (or ls /dev/input/by-id/)" >&2
    exit 1
  fi
  echo "[hookswitch] watching $DEVICE for $HOOK_KEY (debounce ${DEBOUNCE_MS}ms)"
  evtest "$DEVICE" 2>/dev/null | debounce_loop
fi
