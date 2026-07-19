#!/usr/bin/env bash
# Entry point run on autologin: opens Claude Code in a tmux session and
# starts the voice-to-text feeder alongside it.
set -euo pipefail

# The tty1 autologin shell is a login shell and does NOT source ~/.bashrc,
# where the Claude Code installer puts its PATH entry. Without this, `claude`
# isn't found, its tmux pane dies instantly, the session collapses, the
# `exec tmux attach` below fails, the login shell exits, and getty respawns in
# a tight loop until systemd's start-limit kills tty1 (black screen). Make the
# script self-sufficient instead of depending on shell rc files.
export PATH="$HOME/.local/bin:$PATH"

SESSION="${CRT_TMUX_SESSION:-claude}"
PROJECT_DIR="${CRT_PROJECT_DIR:-$HOME}"
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# CRT_MODE=stt  -> standalone speech-to-text only, no Claude Code. A single
# process (crt-stt-solo.py) is the SOLE mic reader -- metering + VAD + whisper
# off one continuous arecord stream. This deliberately avoids the dsnoop meter,
# which on the VirtualBox guest starves a second reader (the bug that made STT
# "stop detecting"). CRT_MODE unset/claude -> the full voice console below.
if [ "${CRT_MODE:-claude}" = "stt" ]; then
  STTSESS="${CRT_STT_SESSION:-sttview}"
  if tmux has-session -t "$STTSESS" 2>/dev/null; then
    exec tmux attach -t "$STTSESS"
  fi
  tmux new-session -d -s "$STTSESS" -c "$BIN_DIR" "python3 ./crt-stt-solo.py; exec bash"
  tmux set-option -t "$STTSESS" status off
  exec tmux attach -t "$STTSESS"
fi

if tmux has-session -t "$SESSION" 2>/dev/null; then
  exec tmux attach -t "$SESSION"
fi

# Wrap each long-running command with `; exec bash` so that if it exits (claude
# quits, stt-feed crashes), it drops to a shell instead of closing -- which would
# otherwise collapse the session and break the attach/respawn loop.
#
# Screen real estate is scarce on the CRT (640x480, big font ~= 40x15 chars), so
# claude gets window 0 to ITSELF -- full screen. stt-feed (and the optional
# hookswitch listener) run in separate *background* windows we never switch to,
# rather than stealing rows as visible split panes. Their transcribed output
# still appears: it gets typed straight into claude's input on window 0.
# Interactive permission prompts are painful hands-free (selecting Yes/No needs
# Enter/arrows). Reduce them: acceptEdits auto-accepts file edits. Set
# CRT_CLAUDE_ARGS='--permission-mode bypassPermissions' for zero prompts (only on
# a console doing your own trusted work), or override entirely as needed.
CLAUDE_ARGS="${CRT_CLAUDE_ARGS:---permission-mode acceptEdits}"
tmux new-session -d -s "$SESSION" -c "$PROJECT_DIR" "claude $CLAUDE_ARGS; exec bash"
tmux new-window -d -t "$SESSION" -n stt -c "$BIN_DIR" "./stt-feed.sh; exec bash"

if [ -n "${CRT_HOOK_DEVICE:-}" ]; then
  tmux new-window -d -t "$SESSION" -n hook -c "$BIN_DIR" "./hookswitch-listen.sh; exec bash"
fi

# Live mic level meter as a thin strip at the bottom of the claude window, so
# you can always see whether your voice is reaching the mic and crossing the VAD
# threshold. Reads the shared dsnoop capture, so it runs alongside stt-feed.
# Set CRT_METER=0 to omit it (reclaim the rows for claude).
if [ "${CRT_METER:-1}" != "0" ]; then
  tmux split-window -t "${SESSION}:0" -v -l 2 -c "$BIN_DIR" "./crt-levels.sh; exec bash"
fi

# Reclaim the bottom row: no tmux status bar on such a small screen.
tmux set-option -t "$SESSION" status off

tmux select-window -t "${SESSION}:0"
tmux select-pane -t "${SESSION}:0.0"
exec tmux attach -t "$SESSION"
