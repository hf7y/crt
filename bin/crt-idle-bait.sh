#!/usr/bin/env bash
# Pops a playful line into thoughts.log (shows on window 1) when the mic's
# been quiet a while, to lure someone into picking up the handset.
set -uo pipefail

LOG="${CRT_THOUGHT_LOG:-$HOME/.crt/thoughts.log}"
STT="${CRT_STT_LOG:-$HOME/.crt/stt.log}"
IDLE_SECS="${CRT_IDLE_BAIT_SECS:-90}"

LINES=(
  "  (=^-^=)  someone pet the cat and say hi, Kristen?"
  "  <('.'<)  dancing here, bored, talk to me Kristen"
  "  ( ._.)   ...anyone? *crickets*"
  "  \\(^o^)/  Kristen, why did the pawn cross the board? for the riddle"
  "  (o.O)?   is this thing on"
  "  ( -_-)zzz  I'd tell a UDP joke but you might not get it"
  "  \\o/       why don't scientists trust atoms? they make up everything"
)

i=0
while true; do
  sleep 10
  last=$(stat -c %Y "$STT" 2>/dev/null || echo 0)
  now=$(date +%s)
  if [ $((now - last)) -ge "$IDLE_SECS" ]; then
    echo "${LINES[$((i % ${#LINES[@]}))]}" >> "$LOG"
    i=$((i + 1))
    sleep "$IDLE_SECS"
  fi
done
