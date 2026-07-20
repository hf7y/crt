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
#   CRT_EARCON_FADE_SCALE=0.3 crt-earcon.sh bait   # clipped/urgent register
#   CRT_EARCON_FADE_SCALE=2.5 crt-earcon.sh bait   # wistful/quiet register
#
# Names (see the `case` below for the actual tone recipe of each):
#   bait      new idle-bait item landed on screen (curiosity-gap chime,
#             fast-ish rise -- "look over here")
#   curious   a gentler, slower rise than `bait` -- "hm, interesting" rather
#             than "psst" -- a real register difference in contour, not
#             just a slower `bait` (see EXPRESSIVE-TONE.md)
#   question  a real judgment call needs Chris (a little more present than
#             `bait`, still not urgent -- see IDLE-BAIT.md's rule that only
#             genuine judgment calls get audio at all)
#   content   something that was pending finally resolved -- rises then
#             settles back down, the "ahh, good" sound
#   success   a job finished clean (bright, quick, satisfied)
#   ack       pickup acknowledged / now listening (a soft click, not a tone
#             -- confirms the line is live without announcing anything)
#   oops      something broke in a way that's actually funny/self-aware,
#             not scary (a little descending "whoop," cartoon-stumble, NOT
#             a klaxon -- reserve real klaxon energy for nothing, ever)
#
# CRT_EARCON_FADE_SCALE (default 1.0) is the "how urgent does this feel
# right now" dial, orthogonal to which tone/contour is picked above -- see
# EXPRESSIVE-TONE.md's register table. Scales every tone's fade-out only
# (attack stays put so the sound is still recognizable at any scale);
# small (~0.3) reads clipped/urgent, large (~2.5+) reads wistful/unhurried.
#
# All idle-bait-triggered calls (bait/curious/question) MUST go through the
# same 15-minute shared lockfile crt-announce.sh uses (CRT_ANNOUNCE_LOCK) so
# a chime and a TV announcement can never stack into a barrage -- enforce
# that at the call site (whatever triggers the earcon), not here; this
# script just plays the sound on request, it doesn't rate-limit itself,
# since `ack`/`success` during an active call should never be throttled.
set -euo pipefail
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

NAME="${1:-}"
shift || true
DEVICE=""
if [ "${1:-}" = "--device" ]; then
  DEVICE="$2"
fi

if [ -z "$NAME" ]; then
  echo "usage: crt-earcon.sh <bait|curious|question|content|success|ack|oops> [--device tv|handset]" >&2
  exit 2
fi

command -v sox >/dev/null 2>&1 || { echo "[crt-earcon] sox not installed" >&2; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

FADE_SCALE="${CRT_EARCON_FADE_SCALE:-1.0}"

note() {  # note <freq> <secs> <out.wav>
  local fadeout
  fadeout=$(awk -v s="$FADE_SCALE" 'BEGIN{v=0.02*s; if (v<0.005) v=0.005; printf "%.3f", v}')
  sox -n -r 22050 "$3" synth "$2" sine "$1" vol 0.5 fade 0.01 "$2" "$fadeout"
}

sweep() {  # sweep <f1> <f2> <secs> <out.wav> -- a true glissando (continuous
  # pitch bend, sox's "f1-f2" frequency syntax) rather than discrete
  # stepped notes -- EXPRESSIVE-TONE.md named this as the un-reached
  # "next pass" (only `oops` used it before 2026-07-20); a real prosodic
  # slide reads as more alive/less robotic than a note sequence for
  # anything meant to feel like a single gesture (a "psst," a "hmm"),
  # while `question`/`content` below still benefit from a little internal
  # shape (a sweep, then a settle) rather than being pure straight lines.
  local fadeout
  fadeout=$(awk -v s="$FADE_SCALE" 'BEGIN{v=0.02*s; if (v<0.005) v=0.005; printf "%.3f", v}')
  sox -n -r 22050 "$4" synth "$3" sine "$1"-"$2" vol 0.5 fade 0.01 "$3" "$fadeout"
}

case "$NAME" in
  bait)
    # single continuous upward slide -- "psst, over here" as one fluid
    # gesture, not two stepped notes.
    sweep 660 880 0.16 "$TMP/out.wav"
    ;;
  curious)
    # slower, gentler slide than `bait` -- a minor third, unhurried. "hm,
    # interesting" rather than "psst, over here."
    sweep 494 587 0.30 "$TMP/out.wav"
    ;;
  question)
    # one continuous rise across the full range, ending on an uptick --
    # closer to actual questioning intonation (which is itself a
    # continuous rise) than three stepped notes were.
    sweep 660 988 0.24 "$TMP/out.wav"
    ;;
  content)
    # rise then settle back down, now as two joined sweeps instead of
    # three stepped notes -- something pending finally resolved, the
    # "ahh, good" contour.
    sweep 523 659 0.14 "$TMP/a.wav"
    sweep 659 587 0.16 "$TMP/b.wav"
    sox "$TMP/a.wav" "$TMP/b.wav" "$TMP/out.wav"
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
    oops_fadeout=$(awk -v s="$FADE_SCALE" 'BEGIN{v=0.03*s; if (v<0.005) v=0.005; printf "%.3f", v}')
    sox -n -r 22050 "$TMP/out.wav" synth 0.25 sine 500-220 vol 0.5 fade 0.01 0.25 "$oops_fadeout"
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
