#!/usr/bin/env bash
# crt console -- SINGLE-READER variant (Approach B in AUDIO-DEBUG.md).
#
# Same as bin/crt-console.sh (full-screen Claude Code, voice typed in), but the
# mic is read by exactly ONE process: bin/crt-stt-solo.py in CRT_STT_SINK=claude
#   [rest: vault:crt/header-archaeology-20260817.md]
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
