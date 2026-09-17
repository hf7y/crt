#!/usr/bin/env bash
# potato pulls crt (crt#325): fast-forward this checkout to origin/main on
# a timer, restart only the tmux windows whose backing script changed.
# Same "pull, not push" shape hf7y/senechal#886 set for dexter's
# containers, applied to a plain checkout instead of an image.
#
# Refuses anything but a clean fast-forward: potato's checkout holds no
# credential and is supposed to hold no local commits either (POTATO.md),
# so a dirty tree or a diverged history means something unexpected
# happened here, and this backs off loud rather than clobbering it.
set -uo pipefail

BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${CRT_PULL_PROJECT_DIR:-$(cd "$BIN_DIR/.." && pwd)}"
SESSION="${CRT_TMUX_SESSION:-claude}"
REMOTE="${CRT_PULL_REMOTE:-origin}"
BRANCH="${CRT_PULL_BRANCH:-main}"
LOG="${CRT_PULL_LOG:-$HOME/.crt/crt-pull.log}"
mkdir -p "$(dirname "$LOG")" 2>/dev/null

log() { printf '%s  %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$LOG" >&2; }

restart_affected_windows() {
  local changed="$1" windows w
  if ! tmux has-session -t "$SESSION" 2>/dev/null; then
    log "no live tmux session '$SESSION', nothing to restart"
    return 0
  fi
  windows="$(printf '%s\n' "$changed" | python3 "$BIN_DIR/crt_console_windows.py" --console "$BIN_DIR/crt-console.sh")"
  if [ -z "$windows" ]; then
    log "no running window's backing script changed"
  fi
  while IFS= read -r w; do
    [ -z "$w" ] && continue
    if tmux respawn-window -k -t "$SESSION:$w" 2>>"$LOG"; then
      log "restarted window '$w' (its backing script changed)"
    else
      log "window '$w' changed but isn't currently running, skipped"
    fi
  done <<<"$windows"
  case "$changed" in
  *crt-console.sh* | *crt-conf.sh*)
    log "crt-console.sh/crt-conf.sh changed -- a window-level restart cannot pick up a layout change (new/removed window, changed launch args); needs a full console restart by hand"
    ;;
  esac
}

cd "$PROJECT_DIR" || {
  log "no project dir at $PROJECT_DIR"
  exit 1
}

if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
  log "dirty tree, refusing to pull"
  exit 1
fi

if ! git fetch -q "$REMOTE" "$BRANCH"; then
  log "fetch from $REMOTE/$BRANCH failed"
  exit 1
fi

before="$(git rev-parse HEAD)"
target="$(git rev-parse "$REMOTE/$BRANCH")"

if [ "$before" = "$target" ]; then
  log "up to date at $before"
  exit 0
fi

changed_files="$(git diff --name-only "$before" "$target")"

if ! git merge -q --ff-only "$REMOTE/$BRANCH"; then
  log "refusing: $before..$target is not a fast-forward (local history diverged)"
  exit 1
fi

log "pulled $before -> $target ($(printf '%s\n' "$changed_files" | grep -c .) file(s) changed)"
restart_affected_windows "$changed_files"
