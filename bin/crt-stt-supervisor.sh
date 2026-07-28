#!/usr/bin/env bash
# Persistent-reattempt supervisor for crt-stt-solo.py (2026-07-28,
# Zach-directed: "need that to be sticky", "wire up noisy fail of usb").
#
# The bug this answers: crt-stt-solo.py's own capture loop already
# handles a *transient* device hiccup (CAPTURE DIED / reopen), but a USB
# replug that makes arecord exit nonzero can take the whole PYTHON
# PROCESS down ("ran 1353s before dying (USB replug? device grabbed by
# another reader?)" -- live 2026-07-28). Nothing restarted it; the
# console silently stopped listening until someone SSH'd in and noticed.
# This script is the thing that notices and restarts, out loud.
#
# Distinct from bin/crt-capture-watchdog.sh: that one detects a STALE
# capture (device present, signal flatlined) via its own dedicated
# peak-monitoring reader -- a different failure shape, VM-era, not
# hardware-verified on potato. This one detects the SOLE READER PROCESS
# ITSELF exiting, which is what actually happened tonight, and needs no
# second capture reader of its own (avoiding any conflict with
# crt-stt-solo.py's "sole reader" design).
#
# Backoff: instant retry the first few times (a real USB replug settles
# in well under a second), then widening delay, capped -- so a
# genuinely-dead device doesn't spin this into a tight loop hammering
# arecord/whisper. A run that stays up past MIN_HEALTHY_SECS resets the
# backoff counter, so one bad stretch doesn't leave the console retrying
# slowly forever after the hardware recovers.
#
# Usage: crt-stt-supervisor.sh   (replaces crt-console.sh's direct
#   `python3 ./crt-stt-solo.py` launch in the `stt` window -- same env
#   vars, all passed through untouched)
# Env (this script's own, on top of everything crt-stt-solo.py reads):
#   CRT_STT_SUP_MIN_HEALTHY_SECS (default 60) -- a run this long resets backoff
#   CRT_STT_SUP_BACKOFF_CAP_SECS (default 30) -- max delay between retries
#   CRT_STT_SUP_ALARM_DEVICE (default $CRT_EARCON_DEVICE, else "tv") --
#     where the crash alarm plays; deliberately defaults toward the loud
#     room-wide path, not the quiet handset, since the whole point is to
#     not be missed
set -uo pipefail

BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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
