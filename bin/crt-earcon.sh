#!/usr/bin/env bash
# Expressive, non-verbal beeps for the crt console -- the "voice" it has
# before/instead of speaking words. Deliberately small, deliberately warm:
# see IDLE-BAIT.md for why these must read as curious/playful, never as an
# alarm (that's the thing that gets the TV turned off).
#   [rest: vault:crt/header-archaeology-20260817.md]
set -euo pipefail
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

NAME="${1:-}"
shift || true
DEVICE=""
if [ "${1:-}" = "--device" ]; then
  DEVICE="$2"
fi

if [ -z "$NAME" ]; then
  echo "usage: crt-earcon.sh <bait|curious|question|content|success|ack|thinking|heard|addressed|control|oops|alarm> [--device tv|handset]" >&2
  exit 2
fi

command -v sox >/dev/null 2>&1 || { echo "[crt-earcon] sox not installed" >&2; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT   # redefined below, once the duck flag exists too

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
  heard)
    # a very short, quiet tick -- deliberately closer to `ack` (a click,
    # not a tone) than to anything melodic, since this is meant to be
    # nearly subliminal even if left on. Quieter (vol 0.25) than the
    # rest of this file's sounds on purpose.
    sox -n -r 22050 "$TMP/out.wav" synth 0.02 sine 350 vol 0.25 fade 0.005 0.02 0.01
    ;;
  addressed)
    # a single clean short note, brighter than `heard` but not as busy as
    # `thinking`'s two-tick pattern -- "yes, that reached me."
    note 494 0.06 "$TMP/out.wav"
    ;;
  control)
    # two quick equal notes, same pitch (not a rise/fall like thinking) --
    # a flat, mechanical double-blip: "keystroke received," not a
    # conversational gesture.
    note 660 0.03 "$TMP/a.wav"
    note 660 0.03 "$TMP/b.wav"
    sox "$TMP/a.wav" "$TMP/b.wav" "$TMP/out.wav"
    ;;
  thinking)
    # two soft rising ticks -- "on it," not a full musical gesture. See
    # the header note above: this is a seed sound, meant to grow into a
    # richer expressive layer later, not the final design.
    note 330 0.04 "$TMP/a.wav"
    note 392 0.04 "$TMP/b.wav"
    sox "$TMP/a.wav" "$TMP/b.wav" "$TMP/out.wav"
    ;;
  oops)
    # descending whoop, cartoon-stumble energy, not a klaxon.
    oops_fadeout=$(awk -v s="$FADE_SCALE" 'BEGIN{v=0.03*s; if (v<0.005) v=0.005; printf "%.3f", v}')
    sox -n -r 22050 "$TMP/out.wav" synth 0.25 sine 500-220 vol 0.5 fade 0.01 0.25 "$oops_fadeout"
    ;;
  alarm)
    # 2026-07-28, Zach-directed exception to this file's own header rule
    # ("never as an alarm, that's the thing that gets the TV turned
    # off") -- reserved exclusively for crt-stt-supervisor.sh's capture-
    # crash signal, where the whole point IS to be impossible to ignore.
    # Three equal, loud, harsh square-wave buzzes -- deliberately
    # nothing like this file's other warm/curious tones. If this ever
    # fires during ordinary use, that is itself the bug report.
    sox -n -r 22050 "$TMP/a.wav" synth 0.12 square 440 vol 0.9
    sox -n -r 22050 "$TMP/b.wav" synth 0.12 square 440 vol 0.9
    sox -n -r 22050 "$TMP/c.wav" synth 0.12 square 440 vol 0.9
    sox -n -r 22050 "$TMP/s.wav" synth 0.06 sine 0 vol 0
    sox "$TMP/a.wav" "$TMP/s.wav" "$TMP/b.wav" "$TMP/s.wav" "$TMP/c.wav" "$TMP/out.wav"
    ;;
  *)
    echo "[crt-earcon] unknown name: $NAME" >&2
    exit 2
    ;;
esac

# Sideband duck (SIDEBAND.md): mute the ambient tone for the duration of
# this earcon, same reasoning/mechanism as crt-tts.py's play_wav -- inert
# unless crt-sideband.sh happens to be running, no opt-in flag needed.
SIDEBAND_MUTE_FILE="${CRT_SIDEBAND_MUTE_FILE:-$HOME/.crt/sideband.mute}"
mkdir -p "$(dirname "$SIDEBAND_MUTE_FILE")" 2>/dev/null || true
: > "$SIDEBAND_MUTE_FILE" 2>/dev/null || true
unduck() { rm -f "$SIDEBAND_MUTE_FILE" 2>/dev/null || true; }
trap 'rm -rf "$TMP"; unduck' EXIT

# Device routing, rewritten 2026-07-23 for potato's real hardware (this
# used to POST to a dexter-hosted audio bridge -- a VirtualBox
# one-sink-per-VM workaround from the old dexter+crt-vm architecture,
# meaningless on bare-metal potato, and the actual reason earcons never
#   [rest: vault:crt/header-archaeology-20260817.md]
TV_DEVICE="${CRT_EARCON_TV_DEVICE:-plughw:2,0}"
HANDSET_DEVICE="${CRT_EARCON_HANDSET_DEVICE:-plughw:1,0}"

# Capture duck (2026-07-24, see crt-tts.py's _capture_mute for the full
# rationale): the handset output is the same USB adapter as the live mic
# capture, and playing on it while crt-stt-solo.py's arecord is running
# leaves the recording near-dead (measured by crt-earcon-loopback-test.py).
#   [rest: vault:crt/header-archaeology-20260817.md]
CTL_FILE="${CRT_CTL_FILE:-$HOME/.crt/ctl}"
CAPTURE_MUTED=0
capture_mute() {
  mkdir -p "$(dirname "$CTL_FILE")" 2>/dev/null || true
  echo "mute $1" >> "$CTL_FILE" 2>/dev/null || true
}
# Unmute via the same EXIT trap as the sideband unduck, not just after a
# successful aplay -- `set -e` means a failed/killed aplay would otherwise
# skip a plain post-aplay "capture_mute 0" and leave capture muted forever.
trap 'rm -rf "$TMP"; unduck; [ "$CAPTURE_MUTED" = 1 ] && capture_mute 0; true' EXIT

# Resolve the device FIRST, then decide about the duck from what the audio
# actually comes out of -- not from the caller having used the word
# "handset". See ducks_capture() in crt-tts.py for the full reasoning; the
# short version is that crt-idle-teaser.sh's chime() and crt-secretary.py's
#   [rest: vault:crt/header-archaeology-20260817.md]
case "$DEVICE" in
  tv)      ALSA_DEVICE="$TV_DEVICE" ;;
  handset) ALSA_DEVICE="$HANDSET_DEVICE" ;;
  *)       ALSA_DEVICE="${DEVICE:-default}" ;;
esac

if [ "$DEVICE" = "handset" ] || [ "$ALSA_DEVICE" = "$HANDSET_DEVICE" ] \
   || [ "$ALSA_DEVICE" = "default" ]; then
  CAPTURE_MUTED=1
  capture_mute 1
fi
aplay -D "$ALSA_DEVICE" -q "$TMP/out.wav"
