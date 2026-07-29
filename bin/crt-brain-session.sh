#!/usr/bin/env bash
# Ensure the tmux session that crt-brain-shell.py drives is alive on the
# brain host (dexter, as of 2026-07-28 -- see DEXTER-MOVE.md).
#
# This is the piece the old mandark bridge never had: there, a human
# started `claude` in a tmux window by hand and the bridge simply assumed
# it. When the session died, every SEND failed with a tmux error and the
# console just went quiet -- correct behavior from the bridge, but nothing
# ever put the brain BACK. Being always-on is the whole reason dexter was
# chosen, so "the session exists" has to be a thing something asserts,
# not a thing someone remembers.
#
# Usage:
#   crt-brain-session.sh ensure    # create if missing (idempotent)
#   crt-brain-session.sh status    # report, exit 1 if absent
#   crt-brain-session.sh restart   # kill and recreate
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# The session name is NOT retyped here. crt-brain-shell.py holds the single
# definition and this asks it, so the authorized_keys forced command and
# this script can never drift onto two different sessions -- which would
# fail in the worst way available: a healthy-looking brain nobody is
# talking to.
SESSION="$("$HERE/crt-brain-shell.py" --print-session)"
if [ -z "$SESSION" ]; then
  echo "crt-brain-session: crt-brain-shell.py --print-session returned nothing" >&2
  exit 2
fi

# Where Claude starts. The crt checkout by default, so the console's brain
# can answer questions about its own project without being told where it
# lives.
CRT_BRAIN_CWD="${CRT_BRAIN_CWD:-$(cd "$HERE/.." && pwd)}"
CLAUDE_BIN="${CRT_BRAIN_CLAUDE:-claude}"

have_session() { tmux has-session -t "$SESSION" 2>/dev/null; }

case "${1:-ensure}" in
  status)
    if have_session; then
      echo "crt-brain-session: $SESSION is UP (cwd $CRT_BRAIN_CWD)"
      exit 0
    fi
    echo "crt-brain-session: $SESSION is DOWN" >&2
    exit 1
    ;;

  restart)
    tmux kill-session -t "$SESSION" 2>/dev/null || true
    ;&

  ensure)
    if have_session; then
      echo "crt-brain-session: $SESSION already up"
      exit 0
    fi

    if ! command -v "$CLAUDE_BIN" >/dev/null 2>&1; then
      echo "crt-brain-session: $CLAUDE_BIN not on PATH -- cannot start the brain" >&2
      exit 2
    fi
    if [ ! -d "$CRT_BRAIN_CWD" ]; then
      echo "crt-brain-session: cwd $CRT_BRAIN_CWD does not exist" >&2
      exit 2
    fi

    tmux new-session -d -s "$SESSION" -c "$CRT_BRAIN_CWD" "$CLAUDE_BIN"

    # Do not report success just because tmux forked. `claude` can exit
    # immediately (not logged in, bad flag) and tmux would still have
    # returned 0 -- the exact exit-0 no-op this project's build discipline
    # names. Re-probe, and give the TUI a moment to actually paint.
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      sleep 1
      have_session || continue
      pane="$(tmux capture-pane -t "$SESSION" -p -S -50 2>/dev/null || true)"
      [ -n "${pane//[[:space:]]/}" ] || continue

      # A painted pane is NOT a ready brain, learned the hard way on
      # dexter 2026-07-28: the first start in an untrusted directory
      # parks on "Do you trust the files in this folder?" and waits.
      # That pane paints beautifully, so the old check called it UP --
      # and every SEND after it would have been typed into a modal
      # dialog and answered by nobody. Name the state instead.
      case "$pane" in
        *"trust the files"*|*"1. Yes, I trust"*)
          echo "crt-brain-session: $SESSION is parked on the trust-folder \
prompt for $CRT_BRAIN_CWD -- not a usable brain. Answer it once with: \
tmux attach -t $SESSION" >&2
          exit 1
          ;;
      esac

      echo "crt-brain-session: $SESSION UP (cwd $CRT_BRAIN_CWD)"
      exit 0
    done

    if have_session; then
      echo "crt-brain-session: $SESSION exists but its pane never painted -- \
claude may have failed to start; check: tmux attach -t $SESSION" >&2
      exit 1
    fi
    echo "crt-brain-session: $SESSION died immediately after start -- \
claude exited. Check credentials: $CLAUDE_BIN -p 'hi'" >&2
    exit 1
    ;;

  *)
    echo "usage: crt-brain-session.sh [ensure|status|restart]" >&2
    exit 2
    ;;
esac
