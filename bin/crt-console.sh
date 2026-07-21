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
SESSION="${CRT_TMUX_SESSION:-claude}"
PROJECT_DIR="${CRT_PROJECT_DIR:-$HOME}"
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# BIN_DIR ahead of ~/.local/bin: this repo's bin/claude shadows the real
# binary to reset leftover terminal mouse-tracking state before every
# launch (see that file's header -- a suspected segfault trigger after a
# Bun/Ink TUI crash). Applies to every `claude` invocation any shell
# forked from this one makes, including a manual re-launch typed after a
# crash drops to the `; exec bash` fallback below.
export PATH="$BIN_DIR:$HOME/.local/bin:$PATH"

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
# quits, stt-solo crashes), it drops to a shell instead of closing -- which would
# otherwise collapse the session and break the attach/respawn loop.
#
# Screen real estate is scarce on the CRT (640x480, big font ~= 40x15 chars), so
# claude gets window 0 to ITSELF -- full screen. Interactive permission prompts
# are painful hands-free (selecting Yes/No needs Enter/arrows). Reduce them:
# acceptEdits auto-accepts file edits. Set
# CRT_CLAUDE_ARGS='--permission-mode bypassPermissions' for zero prompts (only on
# a console doing your own trusted work), or override entirely as needed.
CLAUDE_ARGS="${CRT_CLAUDE_ARGS:---permission-mode acceptEdits}"
tmux new-session -d -s "$SESSION" -c "$PROJECT_DIR" "claude $CLAUDE_ARGS; exec bash"

# Window 1 -- visible "monologue" pane: claude's own DIALOGUE replies (not its
# thinking), pretty-printed and ephemeral (crt-monologue.py fades/drops old
# lines, see that file's own header). This is the one background-feature window
# meant to actually be looked at -- switch to it with prefix+1.
#
# HISTORY (recorded here, not just in a doc, after this exact setup got
# silently lost once already): 2026-07-19 a session hand-built this layout
# (crt-stt-solo.py as sole mic reader + crt-claude-bridge.py + crt-monologue.py)
# ad hoc, in extra tmux windows never wired into this script. It worked live for
# a full evening. Then 2026-07-20, an unrelated VM reboot respawned autologin ->
# this script -> the OLD default (stt-feed.sh + a separate dsnoop meter pane),
# and the better setup was gone with no record it had ever existed beyond
# process-list archaeology. Wiring it in HERE, not just documenting it,
# because code that actually runs on boot is the only kind of "durable" that
# survives a respawn -- a doc is easy to skip. See AUDIO-DEBUG.md "Approach B"
# for the original design writeup and HANDOFF.md for the live-session history.
tmux new-window -d -t "$SESSION" -n mono -c "$BIN_DIR" "./crt-monologue.py; exec bash"

# Background: feeds window 1's log from claude's own transcript (dialogue only,
# see crt-claude-bridge.py's header for why it tails JSONL, not the tmux pane).
tmux new-window -d -t "$SESSION" -n bridge -c "$BIN_DIR" "./crt-claude-bridge.py; exec bash"

# Background: the SOLE mic reader (metering + VAD + whisper + typing into
# window 0), replacing the old stt-feed.sh + crt-levels.sh dsnoop pair --
# see AUDIO-DEBUG.md Approach B for why single-reader avoids that design's
# whole class of staleness bugs. Its own meter/flash HUD writes to this
# window's pane (not visible unless you switch to it), same as before.
tmux new-window -d -t "$SESSION" -n stt -c "$BIN_DIR" \
  "CRT_STT_SINK=claude CRT_TMUX_SESSION=$SESSION CRT_TMUX_PANE=0.0 python3 ./crt-stt-solo.py; exec bash"

if [ -n "${CRT_HOOK_DEVICE:-}" ]; then
  tmux new-window -d -t "$SESSION" -n hook -c "$BIN_DIR" "./hookswitch-listen.sh; exec bash"
fi

# Window: Book Game display (BOOK-GAME.md/BOOK-GAME-STYLE.md). Tails
# ~/.crt/scanner.log -- already written unfiltered by crt-scanner-feed.py
# (SCANNER.md's dexter->crt-vm bridge, live/systemd-persistent as of
# 2026-07-21) -- and renders the centered question screen for each new
# scan. Display-only for this pass: it shows the question, it does not
# grade a spoken answer (still `crt-book-game.py --answer`, run by hand,
# or window 0/secretary wiring later -- BOOK-GAME.md roadmap step 3).
# Unconditional (not gated behind an env var like `hook` above) since the
# scanner bridge itself is a standing systemd service now, not optional
# hardware.
tmux new-window -d -t "$SESSION" -n book -c "$BIN_DIR" "python3 ./crt-book-console.py; exec bash"

# Background: Book Game idle-bait -- pops a cached book quote into
# ~/.crt/thoughts.log (which window "mono" already renders, same as
# claude's own dialogue via the "bridge" window above) after a quiet
# spell. Written but never actually wired into a running window until
# now -- see crt-book-idle-bait.py's own header for the non-API-call
# design (reads books.db/fallback pool only, no live cost at idle time).
tmux new-window -d -t "$SESSION" -n bookidle -c "$BIN_DIR" "python3 ./crt-book-idle-bait.py; exec bash"

# Background: closes the Book Game funnel's last link (idle-bait -> scan
# -> question -> SPOKEN ANSWER -> STT training log, .claude/FOCUS.md's
# 2026-07-21 end-goal). Watches ~/.crt/stt.log (crt-stt-solo.py already
# writes every recognized utterance there, addressed-to-Claude or not)
# for the next utterance after a scan and grades it automatically -- see
# crt-book-answer-listen.py's own header. Prints its own result lines to
# this window's pane (not user-facing chrome, just a debug trail); no
# separate display needed since the question itself is already on the
# `book` window.
tmux new-window -d -t "$SESSION" -n bookanswer -c "$BIN_DIR" "python3 ./crt-book-answer-listen.py; exec bash"

# NOT YET BUILT (flagged explicitly so it doesn't get assumed-done next time):
# a visual signal of the USER's speech (not claude's replies) in the monologue
# window -- e.g. the raw/interim STT text, or just a level indicator. Right now
# window 1 only shows claude's side of the conversation.

# Reclaim the bottom row: no tmux status bar on such a small screen.
tmux set-option -t "$SESSION" status off

# `book` is the default selected window on boot, NOT window 0 (`claude`)
# -- confirmed live 2026-07-21 (hands-on agent, crt-vm) that a physical
# scan's raw keystrokes land in WHICHEVER window has focus, regardless of
# which one "should" have them (SCANNER.md's "2026-07-21 late session"
# finding), and crt-book-console.py now reads its own stdin for exactly
# this reason. Making `book` the boot default is the code-level half of
# that fix (a manual `tmux select-window` was done live but didn't
# survive a respawn/reboot) -- `claude` stays one `prefix+0` away, and
# voice/STT already covers claude-facing interaction without needing
# window 0's focus.
tmux select-window -t "${SESSION}:book"
exec tmux attach -t "$SESSION"
