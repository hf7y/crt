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
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

HOOK_KEY="${CRT_HOOK_KEY:-KEY_F13}"
DEVICE="${CRT_HOOK_DEVICE:-}"   # e.g. /dev/input/by-id/usb-...-event-kbd
DEBOUNCE_MS="${CRT_HOOK_DEBOUNCE_MS:-50}"
DEBOUNCE_S=$(awk -v ms="$DEBOUNCE_MS" 'BEGIN{printf "%.3f", ms/1000}')

# What this signals at. `stt-feed.sh` is the process this file was written
# against in 2026-07-19 -- and crt-console.sh has not run it since
# 2026-07-20, when the sole-mic-reader layout replaced the old
# stt-feed.sh + crt-levels.sh dsnoop pair (see that file's own HISTORY
# comment). So on potato today, `pkill -f stt-feed.sh` matches nothing.
#
# Left pointing where it points (2026-07-25). What on-hook SHOULD do is
# not decidable from the code: SIGSTOP on crt-stt-solo.py stops the reader
# while its arecord child keeps filling the pipe, which is the stale-capture
# class this project has spent cycles on, and the CTL-file mute channel
# (CRT_CTL_FILE, ref-counted, already read live by crt-stt-solo.py) is the
# mechanism actually designed for "suppress capture" -- but choosing
# between them changes what picking up the handset does, which is Zach's
# call and is what FOCUS.md's ranked item 7 already reserves for him. This
# env var is so that call costs a line of config, not an edit.
STT_PROCESS="${CRT_HOOK_STT_PROCESS:-stt-feed.sh}"

apply_state() {
  # 2026-07-25: this printed "pausing STT"/"resuming STT" BEFORE the pkill
  # and swallowed its status with `2>/dev/null || true`, so the one thing
  # it reported was the one thing it had not checked -- for five days it
  # has been announcing a pause it did not perform, against a process name
  # nothing has run since 2026-07-20. Same class as "spoken" not meaning
  # audible (3244250) and a phone that never rang (99a8dc3).
  #
  # The transition itself still prints unconditionally -- that part IS
  # known, the debounce committed it -- and the claim about STT is now
  # whatever pkill actually did.
  local sig verb
  case "$1" in
    on)  sig=STOP; verb=paused ;;
    off) sig=CONT; verb=resumed ;;
    *)   return 0 ;;
  esac
  echo "[hookswitch] $1-hook"
  if pkill -"$sig" -f "$STT_PROCESS" 2>/dev/null; then
    echo "[hookswitch] -> STT $verb (SIG$sig -> $STT_PROCESS)"
    return 0
  fi
  echo "[hookswitch] -> STT NOT $verb: no process matches '$STT_PROCESS'." \
       "The handset moved and the console kept listening." \
       "Set CRT_HOOK_STT_PROCESS to whatever reads the mic here." >&2
  "$BIN_DIR/crt-think.sh" \
    "handset went $1-hook and i carried on listening anyway -- nothing here is called '$STT_PROCESS'" \
    2>/dev/null || true
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
