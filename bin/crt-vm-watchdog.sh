#!/usr/bin/env bash
# Durability net for the live tmux pipeline (crt-console.sh), separate from
# autologin's respawn path. Autologin only refires if the WHOLE tmux session
# dies (tty1's login shell exits) -- see crt-console.sh's own header for that
# mechanism. It does NOT catch a single window's long-running process dying
# quietly into its `; exec bash` fallback (e.g. crt-stt-solo.py crashes,
# window "stt" is now just an idle shell, mic input silently stops with no
# visible signal on a 40x15 screen). This script checks each window's
# expected process is actually alive and respawns just that window's command
# if not, without touching window 0 (claude itself) or losing tmux history.
#
# Run periodically via systemd/crt-vm-watchdog.timer, not continuously --
# this is a check-and-heal pass, not a supervisor daemon.
set -uo pipefail

SESSION="${CRT_TMUX_SESSION:-claude}"
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="$HOME/.crt/watchdog.log"
mkdir -p "$HOME/.crt"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >>"$LOG"; }

if ! tmux has-session -t "$SESSION" 2>/dev/null; then
  log "session '$SESSION' absent -- nothing to heal, autologin owns full respawn"
  exit 0
fi

# window -> (process pattern to look for, command to respawn it with)
declare -A WINDOW_PATTERN=(
  [stt]="crt-stt-solo.py"
  [mono]="crt-monologue.py"
  [bridge]="crt-claude-bridge.py"
)
declare -A WINDOW_CMD=(
  [stt]="CRT_STT_SINK=claude CRT_TMUX_SESSION=$SESSION CRT_TMUX_PANE=0.0 python3 ./crt-stt-solo.py; exec bash"
  [mono]="./crt-monologue.py; exec bash"
  [bridge]="./crt-claude-bridge.py; exec bash"
)

healed=0
for win in "${!WINDOW_PATTERN[@]}"; do
  if ! tmux list-windows -t "$SESSION" -F '#{window_name}' 2>/dev/null | grep -qx "$win"; then
    log "window '$win' missing entirely -- recreating"
    # NOTE: target must be "$SESSION:" (trailing colon) so tmux picks the
    # next free index -- "$SESSION" alone tried to reuse index 0 and failed
    # with "index 0 in use" the first time this was hand-tested live.
    tmux new-window -d -t "$SESSION:" -n "$win" -c "$BIN_DIR" "${WINDOW_CMD[$win]}"
    healed=1
    continue
  fi
  pane_pid=$(tmux list-panes -t "$SESSION:$win" -F '#{pane_pid}' 2>/dev/null | head -1)
  if [ -z "$pane_pid" ]; then
    continue
  fi
  # Process tree under the pane's shell only -- pgrep -P restricts to a
  # direct child of that specific pane, deliberately NOT a bare `pgrep -f`
  # fallback (that matched unrelated command lines, e.g. this very check
  # being run over ssh, as a false "still alive" during testing).
  if pgrep -f -P "$pane_pid" "${WINDOW_PATTERN[$win]}" >/dev/null 2>&1; then
    continue
  fi
  log "window '$win' alive but ${WINDOW_PATTERN[$win]} not running -- respawning"
  tmux respawn-window -k -t "$SESSION:$win" "${WINDOW_CMD[$win]}"
  healed=1
done

# Window 0 (claude itself) is deliberately NOT auto-respawned here: if it
# exits, `; exec bash` leaves a plain shell in the user's face on the CRT,
# which is a legible "something's wrong" signal on a screen with no other
# status indicator. Silently relaunching Claude Code would hide that and
# also lose any conversation-recovery cue. Log it so the report shows it.
claude_pid=$(tmux list-panes -t "$SESSION:0" -F '#{pane_pid}' 2>/dev/null | head -1)
if [ -n "$claude_pid" ] && ! pgrep -f -P "$claude_pid" "claude" >/dev/null 2>&1 && ! pgrep -x "claude" >/dev/null 2>&1; then
  log "window 0 (claude) process not found -- NOT auto-respawning, flagging only"
fi

if [ "$healed" = 1 ]; then
  log "healed one or more windows"
fi
exit 0
