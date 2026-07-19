#!/usr/bin/env bash
# crt console -- SINGLE-READER variant (Approach B in AUDIO-DEBUG.md).
#
# Same as bin/crt-console.sh (full-screen Claude Code, voice typed in), but the
# mic is read by exactly ONE process: bin/crt-stt-solo.py in CRT_STT_SINK=claude
# mode does metering + VAD + whisper + typing off a single continuous arecord
# stream. There is NO dsnoop and NO separate crt-levels meter -- which removes
# the entire class of "second reader starves the capture" staleness the shared
# dsnoop design is prone to on the VirtualBox guest.
#
# Trade-off vs crt-console.sh: the live meter isn't a separate always-on strip;
# it's the bottom line the solo engine itself redraws, shown in a small pane
# that also logs what got typed. If this proves more reliable than the dsnoop
# console, promote it (or wire CRT_CONSOLE=solo into crt-console.sh).
#
# NOT hardware-verified -- written on the dev box (no VM/handset).
#
#   bin/crt-console-solo.sh
set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"

SESSION="${CRT_TMUX_SESSION:-claude}"
PROJECT_DIR="${CRT_PROJECT_DIR:-$HOME}"
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if tmux has-session -t "$SESSION" 2>/dev/null; then
  exec tmux attach -t "$SESSION"
fi

CLAUDE_ARGS="${CRT_CLAUDE_ARGS:---permission-mode acceptEdits}"
tmux new-session -d -s "$SESSION" -c "$PROJECT_DIR" "claude $CLAUDE_ARGS; exec bash"

# The sole mic reader, typing into window 0's Claude pane. Its stdout (meter +
# a log of what it sent) goes to a thin bottom strip; unset CRT_METER to hide.
if [ "${CRT_METER:-1}" != "0" ]; then
  tmux split-window -t "${SESSION}:0" -v -l 3 -c "$BIN_DIR" \
    "CRT_STT_SINK=claude CRT_TMUX_SESSION=$SESSION python3 ./crt-stt-solo.py; exec bash"
else
  tmux new-window -d -t "$SESSION" -n stt -c "$BIN_DIR" \
    "CRT_STT_SINK=claude CRT_TMUX_SESSION=$SESSION python3 ./crt-stt-solo.py >/dev/null 2>&1; exec bash"
fi

# Optional capture watchdog (Approach A) as a background safety net -- it can
# coexist here because it reads its OWN device; set CRT_SOLO_WATCHDOG=1 to add.
if [ "${CRT_SOLO_WATCHDOG:-0}" = "1" ]; then
  tmux new-window -d -t "$SESSION" -n wd -c "$BIN_DIR" \
    "CRT_WD_RESTART_STT=0 ./crt-capture-watchdog.sh; exec bash"
fi

tmux set-option -t "$SESSION" status off
tmux select-window -t "${SESSION}:0"
tmux select-pane -t "${SESSION}:0.0"
exec tmux attach -t "$SESSION"
