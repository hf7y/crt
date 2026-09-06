#!/usr/bin/env bash
# Listens for the hookswitch signal and pauses/resumes stt-feed.sh.
# See HOOKSWITCH.md for the full behavior spec.
#
# Hardware: the printed hook (cad/hook_lever.scad) presses a mini
#   [rest: vault:crt/header-archaeology-20260817.md]
set -uo pipefail
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

HOOK_KEY="${CRT_HOOK_KEY:-KEY_F13}"
DEVICE="${CRT_HOOK_DEVICE:-}"   # e.g. /dev/input/by-id/usb-...-event-kbd
DEBOUNCE_MS="${CRT_HOOK_DEBOUNCE_MS:-50}"
DEBOUNCE_S=$(awk -v ms="$DEBOUNCE_MS" 'BEGIN{printf "%.3f", ms/1000}')

TRANSPORT="${CRT_HOOK_TRANSPORT:-evtest}"   # HOOKSWITCH.md option 3 (Zach, 2026-08-23)
GPIO_PIN="${CRT_HOOK_GPIO_PIN:-}"
GPIO_ACTIVE_LOW="${CRT_HOOK_GPIO_ACTIVE_LOW:-1}"   # 1: pull-up, switch-to-GND on-hook (HOOKSWITCH.md's wiring)
GPIO_KEY="GPIO_HOOK"

# What this signals at. `stt-feed.sh` is the process this file was written
# against in 2026-07-19 -- and crt-console.sh has not run it since
# 2026-07-20, when the sole-mic-reader layout replaced the old
# stt-feed.sh + crt-levels.sh dsnoop pair (see that file's own HISTORY
#   [rest: vault:crt/header-archaeology-20260817.md]
STT_PROCESS="${CRT_HOOK_STT_PROCESS:-stt-feed.sh}"

apply_state() {
  # 2026-07-25: this printed "pausing STT"/"resuming STT" BEFORE the pkill
  # and swallowed its status with `2>/dev/null || true`, so the one thing
  # it reported was the one thing it had not checked -- for five days it
  # has been announcing a pause it did not perform, against a process name
  #   [rest: vault:crt/header-archaeology-20260817.md]
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

# Polled sysfs GPIO read; emits debounce_loop's own "value 0/1" shape (already
# active-low-inverted) so debounce_loop needs no GPIO-specific knowledge.
gpio_loop() {
  local pin="$1" active_low="$2" base gpio_dir poll_s last raw cur
  base="${CRT_HOOK_GPIO_SYSFS_BASE:-/sys/class/gpio}"
  gpio_dir="$base/gpio$pin"
  poll_s=$(awk -v ms="${CRT_HOOK_GPIO_POLL_MS:-20}" 'BEGIN{printf "%.3f", ms/1000}')

  if [ ! -e "$gpio_dir/value" ]; then
    if [ -w "$base/export" ]; then
      echo "$pin" > "$base/export" 2>/dev/null || true
      sleep 0.1
    fi
    if [ ! -e "$gpio_dir/value" ]; then
      echo "[hookswitch] $gpio_dir/value does not exist and export did not create it" >&2
      return 1
    fi
  fi
  [ -w "$gpio_dir/direction" ] && { echo in > "$gpio_dir/direction" 2>/dev/null || true; }

  last=""
  while true; do
    if ! raw="$(cat "$gpio_dir/value" 2>/dev/null)"; then
      echo "[hookswitch] gpio read failed on $gpio_dir/value, exiting" >&2
      return 1
    fi
    raw="${raw//[$'\t\r\n ']/}"
    if [ "$active_low" = "1" ]; then
      [ "$raw" = "0" ] && cur=1 || cur=0
    else
      cur="$raw"
    fi
    if [ "$cur" != "$last" ]; then
      echo "$GPIO_KEY value $cur"
      last="$cur"
    fi
    sleep "$poll_s"
  done
}

# Guarded so tests/test_hookswitch_{debounce,gpio}.sh can `source` this file.
if [ "${CRT_HOOK_TEST_MODE:-0}" = "0" ]; then
  case "$TRANSPORT" in
    gpio)
      if [ -z "$GPIO_PIN" ]; then
        echo "[hookswitch] set CRT_HOOK_GPIO_PIN to the BCM pin the switch is wired to." >&2
        exit 1
      fi
      HOOK_KEY="$GPIO_KEY"
      echo "[hookswitch] watching GPIO$GPIO_PIN for hookswitch (debounce ${DEBOUNCE_MS}ms, active_low=$GPIO_ACTIVE_LOW)"
      gpio_loop "$GPIO_PIN" "$GPIO_ACTIVE_LOW" | debounce_loop
      ;;
    evtest)
      if [ -z "$DEVICE" ]; then
        echo "[hookswitch] set CRT_HOOK_DEVICE to the encoder's /dev/input event node." >&2
        echo "[hookswitch] find it with: evtest  (or ls /dev/input/by-id/)" >&2
        exit 1
      fi
      echo "[hookswitch] watching $DEVICE for $HOOK_KEY (debounce ${DEBOUNCE_MS}ms)"
      evtest "$DEVICE" 2>/dev/null | debounce_loop
      ;;
    *)
      echo "[hookswitch] unknown CRT_HOOK_TRANSPORT '$TRANSPORT' (expected evtest or gpio)" >&2
      exit 1
      ;;
  esac
fi
