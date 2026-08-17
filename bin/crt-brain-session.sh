#!/usr/bin/env bash
# Ensure the tmux session that crt-brain-shell.py drives is alive on the
# brain host (dexter, as of 2026-07-28 -- see DEXTER-MOVE.md).
#
# This is the piece the old mandark bridge never had: there, a human
#   [rest: vault:crt/header-archaeology-20260817.md]
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

# Where Claude starts. The crt checkout, so the console's brain can answer
# questions about its own project without being told where it lives.
#
# But NOT the same working tree a human is editing in. The brain now runs
#   [rest: vault:crt/header-archaeology-20260817.md]
CRT_BRAIN_VOICE_TREE="${CRT_BRAIN_VOICE_TREE:-$HOME/crt-brain}"
if [ -z "${CRT_BRAIN_CWD:-}" ] && [ -d "$CRT_BRAIN_VOICE_TREE" ]; then
  CRT_BRAIN_CWD="$CRT_BRAIN_VOICE_TREE"
fi
CRT_BRAIN_CWD="${CRT_BRAIN_CWD:-$(cd "$HERE/.." && pwd)}"
CLAUDE_BIN="${CRT_BRAIN_CLAUDE:-claude}"

# Zero permission prompts. Not a convenience -- a correctness requirement
# for THIS process, decided by Zach 2026-07-29 after watching it happen.
#
# The brain has no keyboard. Its only input is `tmux send-keys` from
#   [rest: vault:crt/header-archaeology-20260817.md]
CRT_BRAIN_CLAUDE_ARGS="${CRT_BRAIN_CLAUDE_ARGS:---permission-mode bypassPermissions}"

have_session() { tmux has-session -t "$SESSION" 2>/dev/null; }

# A pane that paints is not a brain that answers. Name the states where
# Claude is sitting on a modal waiting for a human who does not exist --
# each one presents as a healthy, beautifully-rendered pane.
parked_reason() {
  case "$1" in
    *"trust the files"*|*"1. Yes, I trust"*)
      echo "parked on the trust-folder prompt for $CRT_BRAIN_CWD" ;;
    *"Do you want to proceed?"*|*"Do you want to make this edit"*|*"Do you want to create"*)
      echo "parked on a permission prompt -- nobody on this end can answer it \
(CRT_BRAIN_CLAUDE_ARGS should carry --permission-mode bypassPermissions)" ;;
    *"Bypass Permissions mode"*|*"accept the risk"*|*"WARNING: Claude Code running in Bypass"*)
      echo "parked on the bypass-permissions confirmation screen" ;;
    *) return 1 ;;
  esac
}

case "${1:-ensure}" in
  status)
    # The installed copy sshd actually runs vs. the repo copy that gets
    # reviewed. These are two files, so they can disagree, and the failure
    # is silent by construction: the console keeps working, just on code
    # nobody read. Report drift here rather than trusting they match.
    installed="${CRT_BRAIN_INSTALLED:-$HOME/.local/bin/crt-brain-shell}"
    if [ -e "$installed" ]; then
      if ! cmp -s "$installed" "$HERE/crt-brain-shell.py"; then
        echo "crt-brain-session: DRIFT -- $installed differs from \
$HERE/crt-brain-shell.py. sshd runs the installed copy, so the repo is NOT \
what is live. Reinstall with: install -m755 $HERE/crt-brain-shell.py $installed" >&2
        drift=1
      fi
    else
      echo "crt-brain-session: $installed is MISSING -- authorized_keys' \
forced command points at a file that does not exist, so every request from \
potato will fail" >&2
      drift=1
    fi

    if have_session; then
      # UP is not the same as ANSWERING. A brain parked on a modal is the
      # worse outcome of the two, because every layer above it reports
      # healthy: the session exists, the pane paints, CAPTURE returns
      # text. It just happens to be the text of a dialog box. Check for
      # it here so `status` can be trusted as the one question worth
      # asking of this session.
      pane="$(tmux capture-pane -t "$SESSION" -p -S -50 2>/dev/null || true)"
      if reason="$(parked_reason "$pane")"; then
        echo "crt-brain-session: $SESSION is UP BUT NOT ANSWERING -- $reason. \
Clear it with: tmux attach -t $SESSION, or restart: $0 restart" >&2
        exit 1
      fi
      echo "crt-brain-session: $SESSION is UP (cwd $CRT_BRAIN_CWD)"
      exit "${drift:-0}"
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

    # Unquoted on purpose: tmux hands this string to sh -c, and
    # CRT_BRAIN_CLAUDE_ARGS is meant to be word-split into flags.
    # shellcheck disable=SC2086
    tmux new-session -d -s "$SESSION" -c "$CRT_BRAIN_CWD" \
      "$CLAUDE_BIN $CRT_BRAIN_CLAUDE_ARGS"

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
      #   [rest: vault:crt/header-archaeology-20260817.md]
      if reason="$(parked_reason "$pane")"; then
        echo "crt-brain-session: $SESSION is $reason -- not a usable brain. \
Clear it with: tmux attach -t $SESSION" >&2
        exit 1
      fi

      echo "crt-brain-session: $SESSION UP (cwd $CRT_BRAIN_CWD, args: \
${CRT_BRAIN_CLAUDE_ARGS:-<none>})"
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
