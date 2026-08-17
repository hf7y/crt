#!/usr/bin/env bash
# Focused, standalone STT view -- no Claude Code. A dedicated screen for
# watching/​tuning speech-to-text: a scrolling log of recognized phrases on top,
# the live mic level meter on the bottom. Use this to confirm the STT pipeline
# works and to calibrate, decoupled from the full console.
#   [rest: vault:crt/header-archaeology-20260817.md]
set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SESSION="${CRT_STT_SESSION:-sttview}"
DEV="${CRT_AUDIO_DEV:-crtmic}"
THR="${CRT_VAD_THRESHOLD:-1.5}"

if tmux has-session -t "$SESSION" 2>/dev/null; then
  exec tmux attach -t "$SESSION"
fi

# Transcription log (top), standalone stt-feed printing timestamped phrases.
tmux new-session -d -s "$SESSION" -c "$BIN_DIR" \
  "CRT_STT_SINK=stdout CRT_AUDIO_DEV=$DEV CRT_VAD_THRESHOLD=$THR ./stt-feed.sh; exec bash"
# Live level meter (bottom strip).
tmux split-window -t "$SESSION" -v -l 2 -c "$BIN_DIR" \
  "CRT_METER_DEV=$DEV CRT_VAD_THRESHOLD=$THR ./crt-levels.sh; exec bash"

tmux set-option -t "$SESSION" status off
tmux select-pane -t "${SESSION}:0.0"
exec tmux attach -t "$SESSION"
