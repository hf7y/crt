#!/usr/bin/env bash
# Background ambient-presence loop (SIDEBAND.md) -- plays a continuous,
# very-quiet, state-dependent texture in the earpiece: silent when idle,
# a faint steady bed while listening, a gently pulsed version while
# thinking, silent again while speaking. Distinct from SIDETONE.md (your
#   [rest: vault:crt/header-archaeology-20260817.md]
set -uo pipefail
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

STATE_FILE="${CRT_SIDEBAND_STATE_FILE:-$HOME/.crt/sideband.state}"
MUTE_FILE="${CRT_SIDEBAND_MUTE_FILE:-$HOME/.crt/sideband.mute}"
CACHE_DIR="${CRT_SIDEBAND_CACHE_DIR:-$HOME/.crt/sideband}"
DEVICE="${CRT_SIDEBAND_DEVICE:-default}"
POLL_S="${CRT_SIDEBAND_POLL:-0.2}"

# Pure: state name -> "silent" or "<base_freq> <pulse_hz> <volume>".
# pulse_hz=0 means a steady tone; nonzero applies a tremolo at that rate.
# Extracted (and guarded below) so tests/test_sideband.sh can call it
# directly without starting the real playback loop.
select_state_spec() {
  case "$1" in
    idle)      echo "silent" ;;
    listening) echo "180 0 0.03" ;;
    thinking)  echo "180 0.5 0.05" ;;
    speaking)  echo "silent" ;;
    *)         echo "silent" ;;
  esac
}

ensure_tone_wav() {
  # $1 = state, $2 = spec ("<freq> <pulse> <vol>"). Prints the cached wav
  # path, generating it with sox if this state's clip doesn't exist yet.
  local state="$1" spec="$2"
  read -r freq pulse vol <<< "$spec"
  local wav="$CACHE_DIR/${state}.wav"
  if [ ! -f "$wav" ]; then
    mkdir -p "$CACHE_DIR"
    if [ "$pulse" = "0" ]; then
      sox -n -r 22050 "$wav" synth 3 sine "$freq" vol "$vol" 2>/dev/null
    else
      sox -n -r 22050 "$wav" synth 3 sine "$freq" vol "$vol" tremolo "$pulse" 60 2>/dev/null
    fi
  fi
  echo "$wav"
}

run_loop() {
  command -v sox >/dev/null 2>&1 || { echo "[sideband] sox not installed" >&2; return 1; }
  command -v aplay >/dev/null 2>&1 || { echo "[sideband] aplay not installed" >&2; return 1; }
  while true; do
    if [ -f "$MUTE_FILE" ]; then
      sleep "$POLL_S"
      continue
    fi
    local state
    state="$(cat "$STATE_FILE" 2>/dev/null || echo idle)"
    local spec
    spec="$(select_state_spec "$state")"
    if [ "$spec" = "silent" ]; then
      sleep "$POLL_S"
      continue
    fi
    local wav
    wav="$(ensure_tone_wav "$state" "$spec")"
    aplay -D "$DEVICE" -q "$wav" 2>/dev/null &
    local pid=$!
    while kill -0 "$pid" 2>/dev/null; do
      sleep "$POLL_S"
      local now_state
      now_state="$(cat "$STATE_FILE" 2>/dev/null || echo idle)"
      if [ "$now_state" != "$state" ] || [ -f "$MUTE_FILE" ]; then
        kill "$pid" 2>/dev/null
        wait "$pid" 2>/dev/null
        break
      fi
    done
  done
}

# Guarded so tests can source this file (to reuse select_state_spec/
# ensure_tone_wav) without starting the real infinite loop.
if [ "${CRT_SIDEBAND_TEST_MODE:-0}" = "0" ]; then
  echo "[sideband] state=$STATE_FILE mute=$MUTE_FILE device=$DEVICE"
  run_loop
fi
