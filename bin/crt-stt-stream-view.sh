#!/usr/bin/env bash
# Standalone viewer for the streaming (LocalAgreement) STT prototype --
# Approach F in AUDIO-DEBUG.md. Mirrors bin/crt-stt.sh's role for the batch
# engine: a dedicated screen to watch/tune crt-stt-stream.py, decoupled from
# the full console, so its live-partial-word behavior can be judged by ear/eye
# without risking the working Claude pipeline.
#
# NOT hardware-verified -- written on the dev box (no VM/handset). The engine
# itself compiles and its transcribe()/local_agreement_commit() logic is
# unit-tested, but nobody has watched partial words scroll on a real CRT yet.
#
#   bin/crt-stt-stream-view.sh
#   CRT_WHISPER_SERVER=http://192.168.0.22:8991/transcribe bin/crt-stt-stream-view.sh
set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SESSION="${CRT_STREAM_SESSION:-sttstream}"
DEV="${CRT_AUDIO_DEV:-plughw:0,0}"
THR="${CRT_VAD_THRESHOLD:-1.0}"

if tmux has-session -t "$SESSION" 2>/dev/null; then
  exec tmux attach -t "$SESSION"
fi

tmux new-session -d -s "$SESSION" -c "$BIN_DIR" \
  "CRT_STT_SINK=stdout CRT_AUDIO_DEV=$DEV CRT_VAD_THRESHOLD=$THR ./crt-stt-stream.py; exec bash"

tmux set-option -t "$SESSION" status off
exec tmux attach -t "$SESSION"
