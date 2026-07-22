#!/usr/bin/env bash
# Wires the CURRENT Claude Code session (wherever this is run from -- an
# SSH debugging conversation, a second terminal, whatever) into the
# physical console's `mono` display, tagged distinctly from window 0's
# own [claude] dialogue (2026-07-21, twelfth pass, Zach's direct ask:
# "show both sessions' output on mono, distinguished somehow").
#
# NOT wired into crt-console.sh's boot sequence on purpose -- there is
# no SSH debugging session most of the time, and auto-starting this with
# no fixed target would just fall back to crt-claude-bridge.py's old
# recency-guessing heuristic, re-introducing the exact bug this session
# spent all night fixing (a bridge picking whichever session was most
# recently active, rather than a specific known one). Run this by hand
# (or have a fresh Claude Code session run it for itself) whenever a
# second live session should be visible on the console too.
#
# Must be run FROM WITHIN the Claude Code session you want mirrored --
# reads $CLAUDE_CODE_SESSION_ID from its own environment (set by Claude
# Code itself for any session, interactive or otherwise) to know which
# transcript to pin to. Run it via Claude Code's own Bash tool (not a
# separate manually-opened shell), since a plain shell won't have that
# env var set at all.
#
#   bin/crt-attach-ssh-bridge.sh                 # tag "ssh", window "sshbridge"
#   CRT_THOUGHT_TAG=debug bin/crt-attach-ssh-bridge.sh   # custom tag/color
#
# Add a NEW color for a custom tag in crt-monologue.py's COLOR_MAP if you
# use something other than "ssh" -- an untagged/unknown tag just falls
# back to DEFAULT_COLOR (plain white), same as any other unrecognized tag.
set -euo pipefail

if [ -z "${CLAUDE_CODE_SESSION_ID:-}" ]; then
  echo "error: \$CLAUDE_CODE_SESSION_ID is not set -- run this from WITHIN a Claude Code session's own Bash tool, not a plain shell." >&2
  exit 1
fi

SESSION="${CRT_TMUX_SESSION:-claude}"
TAG="${CRT_THOUGHT_TAG:-ssh}"
WINDOW_NAME="${CRT_SSH_BRIDGE_WINDOW_NAME:-sshbridge}"
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "error: tmux session '$SESSION' not found -- is the console actually running?" >&2
  exit 1
fi

# Find this session's OWN Claude Code project dir by SEARCHING for its
# transcript file (2026-07-21, found live: deriving the dir name from
# `pwd` -- the Bash tool's CURRENT cwd -- is wrong whenever the
# conversation has `cd`'d around since Claude Code itself launched;
# Claude Code's project-dir naming is fixed at session-START time, not
# tied to whatever directory a later shell command happens to be in).
# Search is fast -- these files are named by UUID, exactly one match.
# `dirname ""` (no match at all) returns "." -- a real, existing
# directory (the script's own cwd) -- so check the FOUND FILE PATH is
# non-empty first, before ever calling dirname on it, rather than
# checking the resulting dir alone (found live: that check silently
# passed with CLAUDE_PROJECT_DIR="." on a no-match, using the wrong
# directory instead of erroring out).
FOUND_TRANSCRIPT="$(find "$HOME/.claude/projects" -maxdepth 2 -iname "${CLAUDE_CODE_SESSION_ID}.jsonl" 2>/dev/null | head -1)"
if [ -z "$FOUND_TRANSCRIPT" ]; then
  echo "error: could not find a transcript file for session $CLAUDE_CODE_SESSION_ID under $HOME/.claude/projects" >&2
  echo "  pass CRT_CLAUDE_PROJECT_DIR explicitly if you know where it actually is." >&2
  exit 1
fi
CLAUDE_PROJECT_DIR="$(dirname "$FOUND_TRANSCRIPT")"

if [ -z "$CLAUDE_PROJECT_DIR" ] || [ ! -d "$CLAUDE_PROJECT_DIR" ]; then
  echo "error: could not find a transcript file for session $CLAUDE_CODE_SESSION_ID under $HOME/.claude/projects" >&2
  echo "  pass CRT_CLAUDE_PROJECT_DIR explicitly if you know where it actually is." >&2
  exit 1
fi

if tmux list-windows -t "$SESSION" -F '#{window_name}' | grep -qx "$WINDOW_NAME"; then
  echo "A window named '$WINDOW_NAME' already exists in session '$SESSION' -- not starting a duplicate." >&2
  echo "Kill it first (tmux kill-window -t $SESSION:$WINDOW_NAME) if you want to reattach with new settings." >&2
  exit 1
fi

# Explicit target index (2026-07-21, found live): `tmux new-window`
# without one can fail with "index 0 in use" on this tmux even when
# indices 0-8 are all legitimately occupied -- doesn't reliably fall
# through to the true next-free slot on its own. Compute it ourselves.
NEXT_INDEX=$(( $(tmux list-windows -t "$SESSION" -F '#{window_index}' | sort -n | tail -1) + 1 ))

tmux new-window -d -t "$SESSION:$NEXT_INDEX" -n "$WINDOW_NAME" -c "$BIN_DIR" \
  "CRT_CLAUDE_SESSION_ID=$CLAUDE_CODE_SESSION_ID CRT_CLAUDE_PROJECT_DIR=${CRT_CLAUDE_PROJECT_DIR:-$CLAUDE_PROJECT_DIR} CRT_THOUGHT_TAG=$TAG ./crt-claude-bridge.py; exec bash"

echo "Attached: session $CLAUDE_CODE_SESSION_ID -> thoughts.log tag [$TAG], tmux window '$SESSION:$WINDOW_NAME'."
echo "Give crt-monologue.py's COLOR_MAP a distinct entry for '$TAG' if it doesn't have one yet (falls back to plain white otherwise)."
