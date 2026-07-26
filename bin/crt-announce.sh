#!/usr/bin/env bash
# Rate-limited TV-facing announcement: speaks a short message through the TV
# audio device (distinct from the phone earpiece device) so Chris can hear a
# simple request without touching anything -- he can only respond by talking
# into the phone. Hard rate limit: at most one announcement per 15 minutes,
# enforced by a lockfile timestamp, so this can be called freely from job
# completion hooks etc. without risking a barrage.
#
# STATUS (2026-07-24): potato is bare-metal, so this now routes through
# crt-tts.py's local-ALSA tv/handset path (plughw:2,0 by default -- see
# crt-tts.py) rather than the old dexter-audio-server.py bridge, which only
# ever applied to the VirtualBox-hosted crt-vm setup (AUDIO-ROUTING.md,
# now legacy). Set CRT_AUDIO_OUT_URL explicitly to restore the old bridge.
#
# Usage: crt-announce.sh "the batch job needs your input"
set -euo pipefail
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

LOCK="${CRT_ANNOUNCE_LOCK:-$HOME/.crt/announce.lastrun}"
MIN_GAP="${CRT_ANNOUNCE_MIN_GAP:-900}"   # 15 minutes
TV_DEV="${CRT_TV_AUDIO_DEV:-tv}"          # dexter-audio-server.py device name

msg="${*:-}"
if [ -z "$msg" ]; then
  echo "usage: crt-announce.sh <message>" >&2
  exit 2
fi

mkdir -p "$(dirname "$LOCK")"
now=$(date +%s)
had_lock=0
last=0
if [ -f "$LOCK" ]; then
  had_lock=1
  last=$(cat "$LOCK" 2>/dev/null || echo 0)
fi
elapsed=$(( now - last ))

if [ "$elapsed" -lt "$MIN_GAP" ]; then
  wait_left=$(( MIN_GAP - elapsed ))
  echo "[crt-announce] rate-limited: last announcement ${elapsed}s ago, need ${MIN_GAP}s. Skipping (would be ready in ${wait_left}s)." >&2
  exit 1
fi

# Stamp BEFORE speaking, then roll the stamp back if nothing was said
# (2026-07-25). Both halves matter and they pull in opposite directions:
#
#   - Stamping first is what stops a barrage. Two hooks firing at once must
#     not produce two overlapping voices on the TV, and the second one is
#     only blocked if the first has already claimed the window. This used to
#     `exec` straight into crt-tts.py, so stamping first was the only
#     option available.
#   - But a stamp that survives a FAILED attempt spends fifteen minutes of
#     silence on an announcement nobody heard -- and the window is shared:
#     crt-idle-teaser.sh's chime() rate-limits against this same file on
#     purpose (IDLE-BAIT.md's single-rate-limit rule), so a TV device that
#     is missing, busy or misnamed would also mute the earpiece chimes. A
#     broken speaker silencing a working one is not a rate limit, it is a
#     fault spreading.
#
# Rolling back on failure keeps the barrage protection (the window IS
# claimed for the duration of the attempt) and gives it up the moment the
# attempt is known to have produced no sound. crt-tts.py's exit status is
# real evidence as of 2026-07-25: play_wav() returns aplay's own verdict
# rather than an unconditional True.
echo "$now" > "$LOCK"
# `status=0; cmd || status=$?` rather than `if cmd; then ... fi; status=$?`:
# an `if` with no else branch that takes the false path leaves `$?` at 0,
# so the obvious spelling would report every failure as exit 0.
status=0
python3 "$BIN_DIR/crt-tts.py" --device "$TV_DEV" "$msg" || status=$?
[ "$status" = 0 ] && exit 0

if [ "$had_lock" = 1 ]; then
  echo "$last" > "$LOCK"
else
  rm -f "$LOCK"
fi

# ...and say so. A TV announcement that failed is exactly the case nobody
# is in the room to notice -- that is what makes it an announcement.
# Window 1 is where this console's honest-failure reports go.
echo "[crt-announce] NOT SPOKEN (crt-tts.py exit $status): $msg" >&2
"$BIN_DIR/crt-think.sh" "tried to say something out loud and the tv stayed quiet: $msg" 2>/dev/null || true
exit "$status"
