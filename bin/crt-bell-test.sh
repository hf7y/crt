#!/usr/bin/env bash
# Watches stt.log for a spoken answer about the bell-tone routing test
# (dexter -> handset earpiece vs TV speaker) and logs findings.
set -uo pipefail

BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STT="${CRT_STT_LOG:-$HOME/.crt/stt.log}"
THOUGHT="${CRT_THOUGHT_LOG:-$HOME/.crt/thoughts.log}"
STATE="${CRT_BELL_TEST_STATE:-$BIN_DIR/../.claude/SESSION-STATE.md}"
PROMPT_SECS=120

echo "did you hear a bell? handset earpiece or TV speaker? just say which." >> "$THOUGHT"

pos=$(wc -l < "$STT" 2>/dev/null || echo 0)
last_prompt=$(date +%s)

while true; do
  sleep 5
  n=$(wc -l < "$STT" 2>/dev/null || echo 0)
  if [ "$n" -gt "$pos" ]; then
    new=$(tail -n $((n - pos)) "$STT")
    pos=$n
    if echo "$new" | grep -qiE "bell|earpiece|handset|speaker|tv"; then
      {
        echo ""
        echo "## Bell-tone routing test — $(date '+%Y-%m-%d %H:%M')"
        echo "Heard: $(echo "$new" | grep -iE 'bell|earpiece|handset|speaker|tv')"
      } >> "$STATE"
      echo "logged that, thanks -- keep going if more tones are coming" >> "$THOUGHT"
      last_prompt=$(date +%s)
    fi
  fi
  now=$(date +%s)
  if [ $((now - last_prompt)) -ge "$PROMPT_SECS" ]; then
    riddles=(
      "riddle while we wait: I speak without a mouth, hear without ears. what am I? (still tracking bell tones btw)"
      "what has keys but no locks, space but no room? (also -- any more bells?)"
      "quick one: what gets wetter the more it dries? (bell test still open)"
    )
    n=${#riddles[@]}
    idx=$(( (now / PROMPT_SECS) % n ))
    echo "${riddles[$idx]}" >> "$THOUGHT"
    last_prompt=$now
  fi
done
