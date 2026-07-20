#!/usr/bin/env bash
# Expressive, non-verbal beeps for the crt console -- the "voice" it has
# before/instead of speaking words. Deliberately small, deliberately warm:
# see IDLE-BAIT.md for why these must read as curious/playful, never as an
# alarm (that's the thing that gets the TV turned off).
#
# STATUS: NOT hardware-verified. sox synth math is correct as designed but
# nobody has listened to these yet -- treat frequencies/durations below as a
# first draft, retune by ear once the VM is reachable.
#
# Usage:
#   crt-earcon.sh <name> [--device tv|handset]
#
# Names (see the `case` below for the actual tone recipe of each):
#   bait      new idle-bait item landed on screen (curiosity-gap chime)
#   question  a real judgment call needs Chris (a little more present than
#             `bait`, still not urgent -- see IDLE-BAIT.md's rule that only
#             genuine judgment calls get audio at all)
#   success   a job finished clean (bright, quick, satisfied)
#   ack       pickup acknowledged / now listening (a soft click, not a tone
#             -- confirms the line is live without announcing anything)
#   oops      something broke in a way that's actually funny/self-aware,
#             not scary (a little descending "whoop," cartoon-stumble, NOT
#             a klaxon -- reserve real klaxon energy for nothing, ever)
#
# All idle-bait-triggered calls (bait/question) MUST go through the same
# 15-minute shared lockfile crt-announce.sh uses (CRT_ANNOUNCE_LOCK) so a
# chime and a TV announcement can never stack into a barrage -- enforce that
# at the call site (whatever triggers the earcon), not here; this script
# just plays the sound on request, it doesn't rate-limit itself, since
# `ack`/`success` during an active call should never be throttled.
set -euo pipefail
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

NAME="${1:-}"
shift || true
DEVICE=""
if [ "${1:-}" = "--device" ]; then
  DEVICE="$2"
fi

if [ -z "$NAME" ]; then
  echo "usage: crt-earcon.sh <bait|question|success|ack|oops> [--device tv|handset]" >&2
  exit 2
fi

command -v sox >/dev/null 2>&1 || { echo "[crt-earcon] sox not installed" >&2; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

note() {  # note <freq> <secs> <out.wav>
  sox -n -r 22050 "$3" synth "$2" sine "$1" vol 0.5 fade 0.01 "$2" 0.02
}

case "$NAME" in
  bait)
    # two soft notes, rising a third -- "psst, over here", not a ring.
    note 660 0.09 "$TMP/a.wav"
    note 880 0.13 "$TMP/b.wav"
    sox "$TMP/a.wav" "$TMP/b.wav" "$TMP/out.wav"
    ;;
  question)
    # three notes, rising -- a little more present than `bait` but still
    # a question mark, not an alarm (ends up, like an actual question).
    note 660 0.08 "$TMP/a.wav"
    note 784 0.08 "$TMP/b.wav"
    note 988 0.14 "$TMP/c.wav"
    sox "$TMP/a.wav" "$TMP/b.wav" "$TMP/c.wav" "$TMP/out.wav"
    ;;
  success)
    # short bright chirp, single note, quick -- satisfied, not celebratory
    # (celebratory gets old fast on the 40th nightly run).
    note 1046 0.10 "$TMP/out.wav"
    ;;
  ack)
    # a soft click: very short, low, no tonal quality to speak of -- reads
    # as "the line picked up," like an old handset relay.
    note 220 0.03 "$TMP/out.wav"
    ;;
  oops)
    # descending whoop, cartoon-stumble energy, not a klaxon.
    sox -n -r 22050 "$TMP/out.wav" synth 0.25 sine 500-220 vol 0.5 fade 0.01 0.25 0.03
    ;;
  *)
    echo "[crt-earcon] unknown name: $NAME" >&2
    exit 2
    ;;
esac

# Same device routing as crt-tts.py: tv/handset go through dexter's audio
# bridge (VirtualBox one-sink-per-VM workaround, see AUDIO-ROUTING.md),
# anything else plays locally. Kept as a plain curl call here rather than
# importing crt-tts.py, since a WAV file, not synthesized speech, is all
# this needs to send.
DEXTER_URL="${CRT_AUDIO_OUT_URL:-http://192.168.0.22:8992/play}"
case "$DEVICE" in
  tv|handset)
    curl -s -X POST --data-binary @"$TMP/out.wav" \
      -H "Content-Type: audio/wav" "$DEXTER_URL?device=$DEVICE" >/dev/null
    ;;
  *)
    aplay -D "${DEVICE:-default}" -q "$TMP/out.wav"
    ;;
esac
