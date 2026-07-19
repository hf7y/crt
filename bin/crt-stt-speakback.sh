#!/usr/bin/env bash
# Runs the standalone STT debug engine (crt-stt-solo.py, stdout sink -- NOT
# wired to Claude Code) and speaks each transcription back through the phone
# earpiece via crt-tts.py, so a person on the handset can debug the mic/STT
# purely by voice/ear, without reading the CRT. Chris-facing debug tool.
#
# STATUS: pipeline verified end-to-end on crt-vm (espeak-ng installed, TTS
# plays with exit 0). NOT confirmed audible by a human yet.
set -uo pipefail
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$BIN_DIR"

export CRT_AUDIO_DEV="${CRT_AUDIO_DEV:-crtmic}"
export CRT_HIGHPASS="${CRT_HIGHPASS:-100}"
export CRT_NOISERED_PROF="${CRT_NOISERED_PROF:-$HOME/crt/noise.prof}"
export CRT_CTL_FILE="${CRT_CTL_FILE:-$HOME/.crt/ctl}"

python3 ./crt-stt-solo.py 2>&1 | while IFS= read -r line; do
  echo "$line"
  # lines look like "14:52:03  some transcribed text" -- strip the timestamp
  text="${line#* }"
  text="${text#*  }"
  case "$line" in
    *"["*"] "*"%"*) continue ;;   # skip the redrawn meter line
  esac
  if [[ "$line" =~ ^[0-9]{2}:[0-9]{2}:[0-9]{2}\ \ (.+)$ ]]; then
    spoken="${BASH_REMATCH[1]}"
    [ -n "$spoken" ] && python3 ./crt-tts.py "heard: $spoken"
  fi
done
