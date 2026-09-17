#!/usr/bin/env bash
set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_DIR="$PROJECT_DIR/bin"
SESSION="${CRT_TMUX_SESSION:-claude}"
GIT="${CRT_PULL_GIT:-git}"
TMUX="${CRT_PULL_TMUX:-tmux}"
LOG="${CRT_PULL_LOG:-$HOME/.crt/pull.log}"

mkdir -p "$(dirname "$LOG")" 2>/dev/null || true
log() { printf '%s  %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$LOG" >&2; }

cd "$PROJECT_DIR"

if [ -n "$("$GIT" status --porcelain)" ]; then
  log "SKIP: working tree dirty, not pulling"
  exit 0
fi

if ! "$GIT" fetch origin main --quiet; then
  log "SKIP: fetch failed"
  exit 0
fi

OLD_HEAD="$("$GIT" rev-parse HEAD)"
NEW_HEAD="$("$GIT" rev-parse origin/main)"

if [ "$OLD_HEAD" = "$NEW_HEAD" ]; then
  log "up to date at $OLD_HEAD"
  exit 0
fi

if ! "$GIT" merge-base --is-ancestor "$OLD_HEAD" "$NEW_HEAD" 2>/dev/null; then
  log "SKIP: origin/main is not a fast-forward from HEAD -- needs a human, not overwriting"
  exit 0
fi

if ! "$GIT" merge --ff-only origin/main --quiet; then
  log "SKIP: fast-forward merge failed unexpectedly"
  exit 0
fi

log "pulled $OLD_HEAD -> $NEW_HEAD"
CHANGED="$("$GIT" diff --name-only "$OLD_HEAD" "$NEW_HEAD")"

restart_window() {
  local win="$1" cmd="$2"
  if "$TMUX" has-session -t "$SESSION" 2>/dev/null \
     && "$TMUX" list-windows -t "$SESSION" -F '#{window_name}' 2>/dev/null | grep -qx "$win"; then
    log "restarting window '$win'"
    "$TMUX" respawn-window -k -t "${SESSION}:${win}" -c "$BIN_DIR" "$cmd; exec bash" 2>/dev/null \
      || log "respawn-window failed for '$win' (may be gone)"
  fi
}

if printf '%s\n' "$CHANGED" | grep -qE '^bin/(crt-stt-supervisor\.sh|crt-stt-solo\.py|crt-conf\.sh|crt-secretary\.py)$'; then
  restart_window stt "CRT_STT_SINK=secretary CRT_STT_GATE=1 CRT_TMUX_SESSION=$SESSION CRT_TMUX_PANE=0.0 ./crt-stt-supervisor.sh"
fi
if printf '%s\n' "$CHANGED" | grep -qE '^bin/crt-monologue\.py$'; then
  restart_window mono "./crt-monologue.py"
fi
if printf '%s\n' "$CHANGED" | grep -qE '^bin/crt-claude-bridge\.py$'; then
  restart_window bridge "./crt-claude-bridge.py"
fi

if printf '%s\n' "$CHANGED" | grep -qE '^bin/crt-console\.sh$'; then
  log "NOTE: bin/crt-console.sh changed -- takes effect next full boot/reattach, not applied live"
fi

exit 0
