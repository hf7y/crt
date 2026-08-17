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

# Real bug found 2026-07-24: this was never set anywhere in the console's
# boot path, so the whole CTL-file live-tune mechanism (crt-ring.sh, the
# "mute" flag crt-tts.py/crt-earcon.sh's handset paths now write to duck
# capture during playback, crt-midi-knobs.py) was silently dead on potato
#   [rest: vault:crt/header-archaeology-20260817.md]
export CRT_CTL_FILE="${CRT_CTL_FILE:-$HOME/.crt/ctl}"

# The console's config -- wake word, earcon sink, mic, whisper server,
# and where the Claude brain runs. All of it read from ~/.crt/ by one
# loader, so this boot path is not the only way to acquire it.
#
# It used to be: these were exports in ~/.bash_profile (which execs this
# script), and the brain block was inline here. Both bit, in the same
# way -- see bin/crt-conf.sh's header for the live 2026-07-29 failure.
# Anything that restarts a window WITHOUT going through a login shell
# came up with library defaults and looked healthy while doing it.
# shellcheck disable=SC1090
. "$BIN_DIR/crt-conf.sh"

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

# Flash the current IP on the real tty (still plain tty1 here, tmux hasn't
# started yet) for CRT_IP_FLASH_SECS before the console takes over --
# mDNS (install.sh's avahi-daemon + CRT_HOSTNAME.local) is the normal way
# to reach this box without knowing its IP, but that only works from the
#   [rest: vault:crt/header-archaeology-20260817.md]
if [ "${CRT_IP_FLASH_SECS:-4}" != "0" ]; then
  IP_ADDRS="$(hostname -I 2>/dev/null | xargs)"
  clear
  echo ""
  echo "  crt console booting..."
  echo "  IP: ${IP_ADDRS:-(none yet -- check network)}"
  echo "  or: $(hostname).local (same network only)"
  echo ""
  sleep "${CRT_IP_FLASH_SECS:-4}"
fi

# Wrap each long-running command with `; exec bash` so that if it exits (claude
# quits, stt-solo crashes), it drops to a shell instead of closing -- which would
# otherwise collapse the session and break the attach/respawn loop.
#
#   [rest: vault:crt/header-archaeology-20260817.md]
if [ "${CRT_NO_IDLE_CLAUDE:-0}" = "1" ]; then
  # Which window is the idle face, written ONCE: the same value selects it
  # at boot (bottom of this file) and tells crt-book-console.py where to
  # hand the tube back after a question times out. Exported before any
  # window is created, so every window inherits it (the CRT_CTL_FILE bug of
  # 2026-07-24 was exactly this, forgotten).
  export CRT_IDLE_FACE_WINDOW="${CRT_IDLE_FACE_WINDOW:-0}"
  # CRT_COLS/ROWS pinned to the tube's real geometry so the screensaver
  # centers correctly even before the tmux client attaches (a detached
  # window is 80x24 until then -- the cause of the earlier line-wrap).
  tmux new-session -d -s "$SESSION" -c "$BIN_DIR" "CRT_COLS=${CRT_COLS:-40} CRT_ROWS=${CRT_ROWS:-15} python3 ./crt-screensaver.py; exec bash"
else
  # In this layout `book` IS the idle face, so there is nowhere to hand the
  # tube back to. Unset rather than assumed-absent: re-running this script
  # in a shell that booted the idle-lean layout earlier would otherwise
  # leave the book window releasing focus to a screensaver that no longer
  # exists on window 0 (a live Claude does).
  unset CRT_IDLE_FACE_WINDOW
  CLAUDE_ARGS="${CRT_CLAUDE_ARGS:---permission-mode acceptEdits}"
  tmux new-session -d -s "$SESSION" -c "$PROJECT_DIR" "claude $CLAUDE_ARGS; exec bash"
fi

# Window 1 -- visible "monologue" pane: claude's own DIALOGUE replies (not its
# thinking), pretty-printed and ephemeral (crt-monologue.py fades/drops old
# lines, see that file's own header). This is the one background-feature window
# meant to actually be looked at -- switch to it with prefix+1.
#   [rest: vault:crt/header-archaeology-20260817.md]
tmux new-window -d -t "$SESSION" -n mono -c "$BIN_DIR" "./crt-monologue.py; exec bash"

# Background: feeds window 1's log from claude's own transcript (dialogue only,
# see crt-claude-bridge.py's header for why it tails JSONL, not the tmux pane).
tmux new-window -d -t "$SESSION" -n bridge -c "$BIN_DIR" "./crt-claude-bridge.py; exec bash"

# Background: the SOLE mic reader (metering + VAD + whisper + typing into
# window 0), replacing the old stt-feed.sh + crt-levels.sh dsnoop pair --
# see AUDIO-DEBUG.md Approach B for why single-reader avoids that design's
# whole class of staleness bugs. Its own meter/flash HUD writes to this
#   [rest: vault:crt/header-archaeology-20260817.md]
tmux new-window -d -t "$SESSION" -n stt -c "$BIN_DIR" \
  "CRT_STT_SINK=secretary CRT_STT_GATE=1 CRT_TMUX_SESSION=$SESSION CRT_TMUX_PANE=0.0 ./crt-stt-supervisor.sh; exec bash"

if [ -n "${CRT_HOOK_DEVICE:-}" ]; then
  tmux new-window -d -t "$SESSION" -n hook -c "$BIN_DIR" "./hookswitch-listen.sh; exec bash"
fi

# Window: Book Game display (BOOK-GAME.md/BOOK-GAME-STYLE.md). Tails
# ~/.crt/scanner.log -- written by crt-book-console.py's OWN stdin path
# (format_scan_log_line(), 2026-07-21 stdin pivot). The old dexter->8993
# HTTP receiver (crt-scanner-feed.py) that used to write this log was
#   [rest: vault:crt/header-archaeology-20260817.md]
tmux new-window -d -t "$SESSION" -n book -c "$BIN_DIR" "python3 ./crt-book-console.py; exec bash"

# Background: Book Game idle-bait -- pops a cached book quote into
# ~/.crt/thoughts.log (which window "mono" already renders, same as
# claude's own dialogue via the "bridge" window above) after a quiet
# spell. Written but never actually wired into a running window until
# now -- see crt-book-idle-bait.py's own header for the non-API-call
# design (reads books.db/fallback pool only, no live cost at idle time).
tmux new-window -d -t "$SESSION" -n bookidle -c "$BIN_DIR" "python3 ./crt-book-idle-bait.py; exec bash"

# Background daemon, not a display surface (2026-07-28, Zach-directed:
# "idlebait also show page92 excerpts via \\192.168.0.27\bibquotes") --
# keeps ~/.crt/bibquotes.txt fresh from bibliothecaire's published-quotes
# Samba share so crt-book-idle-bait.py's own render path can read it with
#   [rest: vault:crt/header-archaeology-20260817.md]
tmux new-window -d -t "$SESSION" -n bibquotes -c "$BIN_DIR" "./crt-bibquotes-sync.sh --daemon; exec bash"

# Background: closes the Book Game funnel's last link (idle-bait -> scan
# -> question -> SPOKEN ANSWER -> STT training log, .claude/FOCUS.md's
# 2026-07-21 end-goal). Watches ~/.crt/stt.log (crt-stt-solo.py already
# writes every recognized utterance there, addressed-to-Claude or not)
#   [rest: vault:crt/header-archaeology-20260817.md]
tmux new-window -d -t "$SESSION" -n bookanswer -c "$BIN_DIR" "python3 ./crt-book-answer-listen.py; exec bash"

# Background: the idle half of "switch to mono when Claude's engaged,
# back to book on idle or by command" (2026-07-21, Zach's direct ask).
# crt-secretary.py's handle() switches TO `mono` the moment a request
# escalates to Claude; this watches for that view going idle and
# switches back to `book` -- see crt-window-switcher.py's own header for
# why this has to be a separate long-running process (crt-secretary.py
# itself is a fresh short-lived process per utterance).
tmux new-window -d -t "$SESSION" -n windowswitch -c "$BIN_DIR" "python3 ./crt-window-switcher.py; exec bash"

# Background: "STT training in the background" (2026-07-21, Zach's direct
# ask) -- periodically recomputes mishear candidates from the accumulated
# Book Game training log (crt-book-game-stats.py's
# generate_candidate_fixups()) and auto-merges new ones straight into the
#   [rest: vault:crt/header-archaeology-20260817.md]
tmux new-window -d -t "$SESSION" -n stttrain -c "$BIN_DIR" "python3 ./crt-stt-training-merge.py --loop; exec bash"

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
#   [rest: vault:crt/header-archaeology-20260817.md]
if [ "${CRT_NO_IDLE_CLAUDE:-0}" = "1" ]; then
  tmux select-window -t "${SESSION}:${CRT_IDLE_FACE_WINDOW}"
else
  tmux select-window -t "${SESSION}:book"
fi
exec tmux attach -t "$SESSION"
