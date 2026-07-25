#!/usr/bin/env bash
# crt audio doctor -- Approach D from AUDIO-DEBUG.md. A RESEARCH instrument, not
# a fix: characterize the capture so we can tell whether the "stops detecting"
# staleness correlates with idle time, utterance boundaries, or a fixed
# interval -- which decides whether the watchdog (A) or single-reader (B) is the
# real fix.
#
# NOT hardware-verified -- written on the dev box (no VM/handset). Read-only wrt
# the pipeline (only reads the mic + reads mixer state); safe to run anytime.
#
#   bin/crt-audio-doctor.sh check              # one-shot health report; exit!=0 if capture looks dead
#   bin/crt-audio-doctor.sh monitor            # append RMS/peak sample every N s to ~/.crt/liveness.csv
#   CRT_DOC_DEV=crtmic bin/crt-audio-doctor.sh check
#
# Tunables (env):
#   CRT_DOC_DEV        capture device (default: resolved by name, see below)
#   CRT_DOC_SECS       sample window per reading, seconds (default 3 for check, 2 for monitor)
#   CRT_DOC_INTERVAL   monitor: seconds between samples (default 10)
#   CRT_DOC_DEAD_PEAK  check: peak below this => "dead" exit code (default 0.004)
#   CRT_ALSA_CARD      mixer card (default: resolved by name, see below)
#   CRT_AUDIO_DEV_NAME name substring to match in `arecord -l` when CRT_DOC_DEV/
#                      CRT_ALSA_CARD aren't set (default "USB Audio", same
#                      lookup crt-stt-solo.py uses -- otherwise this defaulted
#                      to card 0, which is potato's USB mic but mandark's own
#                      onboard card. See crt-lib-audio-device.sh.)
set -uo pipefail

BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./crt-lib-audio-device.sh
source "$BIN_DIR/crt-lib-audio-device.sh"

ARECORD_L="$(arecord -l 2>/dev/null || true)"
DEV="${CRT_DOC_DEV:-$(crt_resolve_capture_device_by_name "$ARECORD_L")}"
CARD="${CRT_ALSA_CARD:-$(crt_resolve_capture_card_by_name "$ARECORD_L")}"
DEAD_PEAK="${CRT_DOC_DEAD_PEAK:-0.004}"
LOGDIR="$HOME/.crt"
CSV="$LOGDIR/liveness.csv"
mkdir -p "$LOGDIR"

# Sample the mic for $1 seconds; echo "rms peak" as fractions of full scale.
# Uses arecord -> python so it shares the exact PCM path the pipeline uses and
# needs no extra deps (no sox stat parsing).
sample() {
  local secs="$1"
  arecord -D "$DEV" -f S16_LE -c1 -r16000 -t raw -d "$secs" 2>/dev/null \
    | python3 -c '
import sys, array, math
raw = sys.stdin.buffer.read()
if len(raw) % 2: raw = raw[:-1]
a = array.array("h"); a.frombytes(raw)
if not a:
    print("0 0"); sys.exit()
peak = max(abs(x) for x in a) / 32768.0
rms = math.sqrt(sum(x*x for x in a) / len(a)) / 32768.0
print("%.6f %.6f" % (rms, peak))
'
}

mixer_line() {
  local src cap
  src=$(amixer -c "$CARD" sget 'Input Source',0 2>/dev/null | grep -o "Item0: '[^']*'" | head -1 | sed "s/Item0: //")
  cap=$(amixer -c "$CARD" sget 'Capture',0 2>/dev/null | grep -o '[0-9]*%' | head -1)
  printf 'InputSource=%s Capture=%s' "${src:-?}" "${cap:-?}"
}

cmd="${1:-check}"
case "$cmd" in
  check)
    secs="${CRT_DOC_SECS:-3}"
    echo "== crt audio doctor: check =="
    echo "device : $DEV"
    echo "cards  :"; printf '%s\n' "$ARECORD_L" | sed 's/^/  /'
    echo "mixer  : $(mixer_line)"
    read -r rms peak < <(sample "$secs")
    printf 'signal : %ss  rms=%.3f%%  peak=%.3f%%\n' "$secs" \
      "$(awk -v v="$rms" 'BEGIN{print v*100}')" \
      "$(awk -v v="$peak" 'BEGIN{print v*100}')"
    if awk -v p="$peak" -v t="$DEAD_PEAK" 'BEGIN{exit !(p < t)}'; then
      echo "verdict: DEAD/STALE -- peak below ${DEAD_PEAK} (capture not delivering signal)"
      exit 1
    fi
    echo "verdict: LIVE"
    ;;
  monitor)
    secs="${CRT_DOC_SECS:-2}"
    interval="${CRT_DOC_INTERVAL:-10}"
    [ -f "$CSV" ] || echo "iso_time,epoch,rms_pct,peak_pct,verdict" > "$CSV"
    echo "monitoring $DEV every ${interval}s -> $CSV (Ctrl-C to stop)"
    while true; do
      read -r rms peak < <(sample "$secs")
      verdict=LIVE
      awk -v p="$peak" -v t="$DEAD_PEAK" 'BEGIN{exit !(p < t)}' && verdict=DEAD
      printf '%s,%s,%.4f,%.4f,%s\n' "$(date -Is)" "$(date +%s)" \
        "$(awk -v v="$rms" 'BEGIN{print v*100}')" \
        "$(awk -v v="$peak" 'BEGIN{print v*100}')" "$verdict" >> "$CSV"
      printf '%s  rms=%.3f%% peak=%.3f%% %s\n' "$(date +%H:%M:%S)" \
        "$(awk -v v="$rms" 'BEGIN{print v*100}')" \
        "$(awk -v v="$peak" 'BEGIN{print v*100}')" "$verdict"
      sleep "$interval"
    done
    ;;
  *)
    echo "usage: $0 {check|monitor}" >&2; exit 2 ;;
esac
