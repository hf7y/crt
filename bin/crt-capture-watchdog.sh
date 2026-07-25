#!/usr/bin/env bash
# crt capture watchdog -- Approach A (+ C keep-alive) from AUDIO-DEBUG.md.
#
# The bug: on the VirtualBox guest the emulated capture intermittently goes
# STALE -- the signal flatlines mid-session while the ALSA mixer still reads
# correct, so stt-feed hears nothing and STT silently "stops detecting". This
# daemon holds ONE continuous reader on the mic, watches the level, and when the
# signal stays flat for too long it RECOVERS the capture (re-asserts the mixer,
# kills stale readers, optionally restarts the stt window so a fresh capture is
# opened).
#
# NOT hardware-verified -- written on the dev box (no VM/handset). Opt-in: it
# touches nothing unless you run it. Intended to run as a background tmux window
# alongside the console, or standalone while debugging.
#
#   bin/crt-capture-watchdog.sh              # watch + recover, log to ~/.crt/watchdog.log
#   CRT_WD_RESTART_STT=1 bin/crt-capture-watchdog.sh   # also bounce the stt tmux window on staleness
#   CRT_WD_KEEPALIVE=1 bin/crt-capture-watchdog.sh     # proactively re-assert mixer periodically (Approach C)
#
# Tunables (env):
#   CRT_WD_DEV            capture device to monitor (default: resolved by
#                         name, see CRT_AUDIO_DEV_NAME below; use a dsnoop
#                         device like 'crtmic' if the console shares one)
#   CRT_WD_FLAT_SECS      seconds of flatline before declaring stale (default 8)
#   CRT_WD_FLAT_PEAK      peak (fraction) below which a chunk counts as "flat"
#                         -- i.e. dead, not speech (default 0.004 = 0.4%)
#   CRT_WD_COOLDOWN       min seconds between recoveries (default 15)
#   CRT_WD_KEEPALIVE      1 = periodically re-assert mixer even when healthy
#   CRT_WD_KEEPALIVE_SECS keep-alive interval (default 60)
#   CRT_WD_RESTART_STT    1 = on staleness, respawn the 'stt' window in $CRT_TMUX_SESSION
#   CRT_ALSA_CARD         mixer card (default: resolved by name, see below)
#   CRT_INPUT_SOURCE      capture source to re-assert (default Line)
#   CRT_AUDIO_DEV_NAME    name substring to match in `arecord -l` when
#                         CRT_WD_DEV/CRT_ALSA_CARD aren't set (default
#                         "USB Audio" -- otherwise this defaulted to card 0,
#                         which is a different device on every box. See
#                         crt-lib-audio-device.sh.)
set -uo pipefail

BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./crt-lib-audio-device.sh
source "$BIN_DIR/crt-lib-audio-device.sh"

ARECORD_L="$(arecord -l 2>/dev/null || true)"
DEV="${CRT_WD_DEV:-$(crt_resolve_capture_device_by_name "$ARECORD_L")}"
FLAT_SECS="${CRT_WD_FLAT_SECS:-8}"
FLAT_PEAK="${CRT_WD_FLAT_PEAK:-0.004}"
COOLDOWN="${CRT_WD_COOLDOWN:-15}"
KEEPALIVE="${CRT_WD_KEEPALIVE:-0}"
KEEPALIVE_SECS="${CRT_WD_KEEPALIVE_SECS:-60}"
RESTART_STT="${CRT_WD_RESTART_STT:-0}"
CARD="${CRT_ALSA_CARD:-$(crt_resolve_capture_card_by_name "$ARECORD_L")}"
INPUT_SOURCE="${CRT_INPUT_SOURCE:-Line}"
SESSION="${CRT_TMUX_SESSION:-claude}"

LOGDIR="$HOME/.crt"
mkdir -p "$LOGDIR"
LOG="$LOGDIR/watchdog.log"

log() { printf '%s  %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$LOG" >&2; }

reassert_mixer() {
  if amixer -c "$CARD" sget 'Input Source',0 2>/dev/null | grep -q "'$INPUT_SOURCE'"; then
    amixer -c "$CARD" sset 'Input Source',0 "$INPUT_SOURCE" >/dev/null 2>&1 || true
    amixer -c "$CARD" sset 'Input Source',1 "$INPUT_SOURCE" >/dev/null 2>&1 || true
  fi
  amixer -c "$CARD" sset 'Capture',0 100% cap >/dev/null 2>&1 || true
  amixer -c "$CARD" sset 'Capture',1 100% cap >/dev/null 2>&1 || true
}

recover() {
  log "STALE: signal flat > ${FLAT_SECS}s -- recovering capture"
  reassert_mixer
  # Kill stale per-utterance readers that may be holding the emulated device in
  # a bad state (our own always-open reader is excluded via its PID below).
  pkill -f 'arecord .*(plughw|crtmic|hw:)' 2>/dev/null || true
  pkill -f 'sox .*silence' 2>/dev/null || true
  if [ "$RESTART_STT" = "1" ] && tmux has-session -t "$SESSION" 2>/dev/null; then
    if tmux list-windows -t "$SESSION" -F '#{window_name}' 2>/dev/null | grep -qx stt; then
      log "bouncing '$SESSION:stt' window"
      tmux respawn-window -k -t "${SESSION}:stt" -c "$BIN_DIR" "./stt-feed.sh; exec bash" 2>/dev/null \
        || log "respawn-window failed (window may be gone)"
    fi
  fi
  log "recovery done"
}

# Read the mic as raw PCM and print one peak fraction per 100 ms chunk. Kept as
# a co-process so the bash loop below owns timing/recovery. If arecord dies
# (device hiccup) the loop notices via a read timeout and reopens.
peak_stream() {
  arecord -D "$DEV" -f S16_LE -c1 -r16000 -t raw 2>/dev/null \
    | python3 "$BIN_DIR/crt-meter.py" --peaks 2>/dev/null
}

log "watchdog start: dev=$DEV flat>${FLAT_SECS}s@${FLAT_PEAK} cooldown=${COOLDOWN}s keepalive=$KEEPALIVE restart_stt=$RESTART_STT"
reassert_mixer

last_recovery=0
last_keepalive=$(date +%s)
while true; do
  flat_start=""
  # Read peaks; `read -t` bounds how long we block so a dead arecord (no output)
  # is itself detected as flat.
  while IFS= read -r -t 2 peak; do
    now=$(date +%s)
    # Keep-alive (Approach C): periodically re-assert the mixer even when healthy.
    if [ "$KEEPALIVE" = "1" ] && [ $((now - last_keepalive)) -ge "$KEEPALIVE_SECS" ]; then
      reassert_mixer
      last_keepalive=$now
    fi
    # Is this chunk "flat" (dead), i.e. below FLAT_PEAK?
    if awk -v p="$peak" -v t="$FLAT_PEAK" 'BEGIN{exit !(p < t)}'; then
      [ -z "$flat_start" ] && flat_start=$now
      if [ $((now - flat_start)) -ge "$FLAT_SECS" ] && [ $((now - last_recovery)) -ge "$COOLDOWN" ]; then
        recover
        last_recovery=$(date +%s)
        flat_start=""
      fi
    else
      flat_start=""   # live signal seen -> reset the flat timer
    fi
  done < <(peak_stream)
  # peak_stream ended (arecord exited / read timed out with no data): treat as a
  # hard staleness too, then reopen.
  now=$(date +%s)
  if [ $((now - last_recovery)) -ge "$COOLDOWN" ]; then
    log "reader ended/timed out -- treating as stale"
    recover
    last_recovery=$now
  fi
  sleep 0.5
done
