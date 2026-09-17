#!/usr/bin/env bash
# potato-only: fast-forward ~/crt to origin/main and restart whatever tmux
# window the changed files feed, so a merge becomes a deploy with no scp
# and no human on potato (hf7y/crt#325, "hosts pull" ruling on
# hf7y/senechal#886 -- the pattern already adopted for dexter's
# containers via srv-reconcile).
#
# Never touches a dirty tree or a diverged one (local commits not on
# origin/main, e.g. from crt-self-repair.sh) -- both are left for a human
# to resolve, not force-merged over.
set -uo pipefail

PROJECT_DIR="${CRT_PULL_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
LOG="${CRT_PULL_LOG:-$HOME/.crt/crt-pull.log}"
SESSION="${CRT_TMUX_SESSION:-claude}"
mkdir -p "$(dirname "$LOG")" 2>/dev/null

say() { printf '%s  %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" | tee -a "$LOG"; }

cd "$PROJECT_DIR" || { say "RED  cannot cd to $PROJECT_DIR"; exit 1; }

if ! git fetch -q origin main 2>>"$LOG"; then
  say "RED  git fetch origin main failed"
  exit 1
fi

if [ -n "$(git status --porcelain)" ]; then
  say "SKIP  working tree is dirty, not pulling"
  exit 0
fi

local_head="$(git rev-parse HEAD)"
remote_head="$(git rev-parse origin/main)"

if [ "$local_head" = "$remote_head" ]; then
  say "GREEN  already at origin/main ($(git rev-parse --short HEAD))"
  exit 0
fi

base="$(git merge-base HEAD origin/main)"
if [ "$base" != "$local_head" ]; then
  say "SKIP  local HEAD has commits origin/main doesn't -- not a fast-forward, left for a human"
  exit 0
fi

changed="$(git diff --name-only HEAD origin/main)"

if ! git merge -q --ff-only origin/main 2>>"$LOG"; then
  say "RED  ff-only merge failed even though it looked fast-forwardable"
  exit 1
fi

say "GREEN  pulled $(git rev-parse --short "$local_head")..$(git rev-parse --short "$remote_head")"

# piece name -> tmux window it runs in -> the files that mean "restart it"
restart_piece() {  # restart_piece <window> <pattern...>
  local window="$1"; shift
  local pat
  for pat in "$@"; do
    if printf '%s\n' "$changed" | grep -q "^$pat"; then
      if command -v tmux >/dev/null 2>&1 && tmux has-session -t "$SESSION" 2>/dev/null \
         && tmux list-windows -t "$SESSION" -F '#{window_name}' 2>/dev/null | grep -qx "$window"; then
        tmux respawn-window -k -t "$SESSION:$window"
        say "GREEN  restarted window '$window' (changed: $pat)"
      else
        say "SKIP  would restart window '$window' (changed: $pat) -- no live '$SESSION' session"
      fi
      return
    fi
  done
}

# window 0 (screensaver or a resident Claude) is deliberately NOT restarted
# here -- it may hold a live, mid-conversation Claude session, and killing
# that is a bigger call than this timer should make unattended.
restart_piece stt \
  bin/crt-stt-supervisor.sh bin/crt-stt-solo.py bin/crt-conf.sh \
  bin/crt_wake_gate.py bin/crt-stt-confidence.py bin/crt_fixups_store.py \
  stt-fixups.json
restart_piece mono bin/crt-monologue.py
restart_piece bridge bin/crt-claude-bridge.py
restart_piece hook bin/hookswitch-listen.sh
