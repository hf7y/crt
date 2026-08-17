#!/usr/bin/env bash
# Persistent-reattempt supervisor for crt-stt-solo.py (2026-07-28,
# Zach-directed: "need that to be sticky", "wire up noisy fail of usb").
#
# The bug this answers: crt-stt-solo.py's own capture loop already
#   [rest: vault:crt/header-archaeology-20260817.md]
set -uo pipefail

BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Read the console's config HERE rather than trusting whatever env this
# window happened to be launched with (2026-07-29). This script is the
# restart point for capture -- when the ears need to come back, this is
# what gets rerun, and it is routinely rerun by hand from an ssh shell
# that never sourced ~/.bash_profile. That is exactly how a console came
# up beeping into the handset and answering to "claude" instead of
# "potato", with nothing in any log to say so. crt-conf.sh's files use
# the ${VAR:-default} form, so an env var crt-console.sh (or a human
# testing something) passed in still wins.
# shellcheck disable=SC1090
. "$BIN_DIR/crt-conf.sh"

LOG="$HOME/.crt/stt-supervisor.log"
mkdir -p "$(dirname "$LOG")"

MIN_HEALTHY_SECS="${CRT_STT_SUP_MIN_HEALTHY_SECS:-60}"
BACKOFF_CAP_SECS="${CRT_STT_SUP_BACKOFF_CAP_SECS:-30}"
ALARM_DEVICE="${CRT_STT_SUP_ALARM_DEVICE:-${CRT_EARCON_DEVICE:-tv}}"

log() { printf '%s  %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$LOG" >&2; }

alarm() {
  # Fire-and-forget, same posture as every other earcon call in this
  # project: the supervisor's own job (getting capture back up) must
  # never wait on or be blocked by the alarm sound itself.
  "$BIN_DIR/crt-earcon.sh" alarm --device "$ALARM_DEVICE" >/dev/null 2>&1 &
}

crashes=0
log "supervisor start (min_healthy=${MIN_HEALTHY_SECS}s backoff_cap=${BACKOFF_CAP_SECS}s alarm_device=${ALARM_DEVICE})"

while true; do
  started=$(date +%s)
  log "launching crt-stt-solo.py (crash count so far: $crashes)"
  python3 "$BIN_DIR/crt-stt-solo.py"
  code=$?
  ended=$(date +%s)
  ran_secs=$((ended - started))

  if [ "$ran_secs" -ge "$MIN_HEALTHY_SECS" ]; then
    crashes=0
  else
    crashes=$((crashes + 1))
  fi

  log "crt-stt-solo.py exited $code after ${ran_secs}s -- restarting (crash #$crashes)"
  alarm

  # 0s, 0s, 1s, 2s, 4s, 8s, 16s, 30s(cap), 30s, ... -- instant for the
  # first couple (a real replug is already over by the time this notices),
  # widening after that.
  if [ "$crashes" -le 2 ]; then
    delay=0
  else
    delay=$(( 1 << (crashes - 3) ))
    [ "$delay" -gt "$BACKOFF_CAP_SECS" ] && delay="$BACKOFF_CAP_SECS"
  fi
  [ "$delay" -gt 0 ] && sleep "$delay"
done
