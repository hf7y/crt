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
#   thinking  added 2026-07-23 (live latency-tuning session): fires the
#             instant crt-secretary.py escalates to Claude, before
#             wait_for_claude_reply()'s real (multi-second) round-trip --
#             kills the dead-air feeling that made the wait read as
#             "broken" rather than "working." Deliberately a single fixed
#             sound for now (two soft rising ticks, "on it") -- the
#             intended evolution (not built yet) is a whole expressive
#             layer here: contour/urgency could vary with expected wait
#             length, escalation type (secretary fallthrough vs confirmed
#             playbook), or elapsed time if a reply is running long. Treat
#             this one sound as the seed of that, not the final design.
#   oops      something broke in a way that's actually funny/self-aware,
#             not scary (a little descending "whoop," cartoon-stumble, NOT
#             a klaxon -- reserve real klaxon energy for nothing, ever)
#   heard     added 2026-07-23: VAD threshold crossed, an utterance is
#             being captured -- lowest-stakes, highest-frequency sound in
#             this whole file (fires on ALL room speech, not just
#             wake-worded requests -- see crt-stt-solo.py's
#             CRT_EARCON_ON_THRESHOLD, default OFF for exactly that
#             reason). A single very short, quiet tick -- must stay
#             nearly subliminal if it's ever turned on for real, not a
#             per-sentence intrusion.
#   addressed added 2026-07-23: the STT wake-word gate passed (request is
#             actually addressed to the console, whether or not it later
#             matches a local playbook or escalates to Claude) -- fires
#             in crt-stt-solo.py right after addressed_to_console()
#             succeeds, earlier than `thinking` (which only fires for the
#             Claude-escalation branch specifically).
#   control   added 2026-07-23: a single-word CONTROL keystroke was
#             recognized (yes/no/enter/up/down/etc, see CONTROL dict) --
#             the "watchword" gate, structurally separate from the
#             addressed/gate-drop wake-word path since control words
#             bypass that gate entirely.
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
  echo "usage: crt-earcon.sh <bait|curious|question|content|success|ack|thinking|heard|addressed|control|oops> [--device tv|handset]" >&2
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
# reached the TV/handset here: DEXTER_URL pointed at a host/service that
# doesn't exist in this architecture at all). Confirmed live 2026-07-23
# by ear (Zach on the handset): plughw:2,0 (card 2, vc4-hdmi) is the
# TV/RF-modulator path; plughw:1,0 (card 1, "KT USB Audio" -- the same
# USB device the mic itself uses) is the handset earpiece. `plug` (not
# bare `hw`) because these devices don't accept sox's raw synth format
# directly (tested: bare hw:2,0 fails with "Sample format non
# available", hw:1,0 fails with "Channels count non available").
TV_DEVICE="${CRT_EARCON_TV_DEVICE:-plughw:2,0}"
HANDSET_DEVICE="${CRT_EARCON_HANDSET_DEVICE:-plughw:1,0}"

# Capture duck (2026-07-24, see crt-tts.py's _capture_mute for the full
# rationale): the handset output is the same USB adapter as the live mic
# capture, and playing on it while crt-stt-solo.py's arecord is running
# leaves the recording near-dead (measured by crt-earcon-loopback-test.py).
# Suppress VAD triggering for the duration via the same CTL-file "mute"
# reference count crt-tts.py's handset path now uses (ref-counted, not a
# last-write-wins flag, so this can't unmute early out from under a
# concurrent TTS duck), so a played tone can't be misread as speech while
# the adapter can't hear the room anyway.
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

case "$DEVICE" in
  tv)
    aplay -D "$TV_DEVICE" -q "$TMP/out.wav"
    ;;
  handset)
    CAPTURE_MUTED=1
    capture_mute 1
    aplay -D "$HANDSET_DEVICE" -q "$TMP/out.wav"
    ;;
  *)
    aplay -D "${DEVICE:-default}" -q "$TMP/out.wav"
    ;;
esac
