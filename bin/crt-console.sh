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

# Where the console's Claude brain runs is a runtime choice Zach flips with
# bin/crt-mandark.sh, persisted to ~/.crt/mandark.conf (sets
# CRT_CLAUDE_REMOTE_PORT: a real port -> route escalations to mandark's
# remote Claude bridge; 0 -> keep it local/onsite). Sourcing it here lets
# that toggle survive a reboot without editing this file. No file = the
# historical default (remote on, port 8993), preserved by the `:-8993`
# fallback on the stt window's launch line below. See POTATO.md.
CRT_MANDARK_CONF="${CRT_MANDARK_CONF:-$HOME/.crt/mandark.conf}"
if [ -f "$CRT_MANDARK_CONF" ]; then
  # shellcheck disable=SC1090
  . "$CRT_MANDARK_CONF"
fi

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
# SAME LAN segment (multicast doesn't cross routers/VLANs); this is the
# fallback that works regardless, and the only option at all if avahi
# isn't installed/running. Only on a genuine fresh boot (the has-session
# check above already exited for a reattach), so this never interrupts an
# already-running console.
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
# Screen real estate is scarce on the CRT (640x480, big font ~= 40x15 chars), so
# claude gets window 0 to ITSELF -- full screen. Interactive permission prompts
# are painful hands-free (selecting Yes/No needs Enter/arrows). Reduce them:
# acceptEdits auto-accepts file edits. Set
# CRT_CLAUDE_ARGS='--permission-mode bypassPermissions' for zero prompts (only on
# a console doing your own trusted work), or override entirely as needed.
# CRT_NO_IDLE_CLAUDE=1 -> idle-lean layout: hold NO Claude brain on potato
# while idle (Claude Code was ~37% of this 1GB Pi's RAM --
# ARCHITECTURE-REVIEW-2026-07-23.md). Window 0 shows the potato
# screensaver instead of a resident Claude; escalations route to mandark's
# remote Claude over the bridge (CRT_CLAUDE_REMOTE_PORT). If mandark is
# down, the onsite fallback brain is meant to be spun up on demand by a
# wake supervisor -- that supervisor is the ONE remaining piece of live
# wiring (see POTATO.md "remaining live wiring"); until it exists,
# mandark-down in this mode degrades to a short honest reply, not a crash.
# Default (unset/0) keeps the historical always-resident-Claude layout,
# so nothing regresses unless this is deliberately turned on and
# live-verified. crt-wake-router.py is the decision brain either way.
if [ "${CRT_NO_IDLE_CLAUDE:-0}" = "1" ]; then
  # CRT_COLS/ROWS pinned to the tube's real geometry so the screensaver
  # centers correctly even before the tmux client attaches (a detached
  # window is 80x24 until then -- the cause of the earlier line-wrap).
  tmux new-session -d -s "$SESSION" -c "$BIN_DIR" "CRT_COLS=${CRT_COLS:-40} CRT_ROWS=${CRT_ROWS:-15} python3 ./crt-screensaver.py; exec bash"
else
  CLAUDE_ARGS="${CRT_CLAUDE_ARGS:---permission-mode acceptEdits}"
  tmux new-session -d -s "$SESSION" -c "$PROJECT_DIR" "claude $CLAUDE_ARGS; exec bash"
fi

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
#
# CRT_STT_SINK=secretary (2026-07-21, Zach's direct call): every utterance
# used to be typed straight into the live Claude pane (SINK=claude) --
# real cost/attention problem per FOCUS.md's original STT-gate note, and
# not what the Book Game needs (that funnel already reads ~/.crt/stt.log
# directly in crt-book-answer-listen.py, unconditionally, so it never
# depended on this sink value). secretary mode routes non-control
# utterances through crt-secretary.py's playbook dispatcher instead,
# escalating to Claude only on fallthrough (crt-secretary.py's own
# design intent, "call out to API when unsure"). Control keystrokes
# (yes/no/enter/etc) still go straight to tmux either way -- see
# crt-stt-solo.py's own SINK branch for the exact split.
#
# CRT_STT_GATE=1 (2026-07-21, same call, found live): SINK=secretary alone
# wasn't enough -- casual room conversation almost never matches one of
# secretary's playbooks, so it was still escalating to Claude on
# fallthrough nearly every time, functionally unchanged from SINK=claude.
# The wake-word gate (built 2026-07-20, never turned on) drops anything
# that doesn't contain "claude" (or a confirmed stt-fixups.json mishear of
# it, e.g. "slide") before it reaches secretary/Claude at all -- dropped
# lines get logged to thoughts.log, not silently discarded. Control
# keystrokes bypass the gate entirely (see addressed_to_console's callers).
# CRT_AUDIO_DEV pinned to plughw:1,0 2026-07-23 (live session): potato's
# mic (KT USB Audio) only ever shows up as a CAPTURE device on card 1 --
# card 0 (bcm2835, onboard) is playback-only, has no capture subdevice at
# all. crt-stt-solo.py's own default (plughw:0,0) is a leftover from a
# different box's card layout; a real USB reconnect event happened
# mid-session tonight (dmesg-confirmed, ~01:25) and exposed this the hard
# way when the sole-reader process got restarted after it -- silent exit,
# no capture, no error. Hardcoding a card INDEX at all is fragile (any
# USB replug/reboot can renumber it) -- see FOCUS.md's 2026-07-23 note
# for the real fix (resolve by device name via `arecord -l`, not index).
# CRT_CLAUDE_REMOTE_PORT set 2026-07-23 (live session): the actual
# Claude Code process now runs on mandark, not potato -- see
# bin/crt-remote-claude-bridge.py's header for the full design (a
# 127.0.0.1-only bridge server on mandark, reverse-tunneled in by
# mandark's own outbound ssh -- potato never gets a network path INTO
# mandark). Requires the bridge server running on mandark AND the
# reverse tunnel (`ssh -R 8993:localhost:8993 potato -N`) both up before
# this window starts, or every escalation will just time out empty.
tmux new-window -d -t "$SESSION" -n stt -c "$BIN_DIR" \
  "CRT_STT_SINK=secretary CRT_STT_GATE=1 CRT_TMUX_SESSION=$SESSION CRT_TMUX_PANE=0.0 CRT_WHISPER_SERVER=${CRT_WHISPER_SERVER:-http://192.168.0.27:8991/transcribe} CRT_AUDIO_DEV=${CRT_AUDIO_DEV:-plughw:1,0} CRT_CLAUDE_REMOTE_PORT=${CRT_CLAUDE_REMOTE_PORT:-8993} python3 ./crt-stt-solo.py; exec bash"

if [ -n "${CRT_HOOK_DEVICE:-}" ]; then
  tmux new-window -d -t "$SESSION" -n hook -c "$BIN_DIR" "./hookswitch-listen.sh; exec bash"
fi

# Window: Book Game display (BOOK-GAME.md/BOOK-GAME-STYLE.md). Tails
# ~/.crt/scanner.log -- written by crt-book-console.py's OWN stdin path
# (format_scan_log_line(), 2026-07-21 stdin pivot). The old dexter->8993
# HTTP receiver (crt-scanner-feed.py) that used to write this log was
# RETIRED 2026-07-23 (Zach: "kill scanner feed, keep claude") -- it
# collided with the remote-Claude bridge's tunnel on port 8993 and was
# dexter-legacy dead weight on potato. -- and renders the centered
# question screen for each new
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
# live stt-fixups.json, tagged confidence:"auto", never touching an
# existing (human-reviewed) entry -- see crt-stt-training-merge.py's own
# header for the honest scope note: today's only consumer of
# stt-fixups.json is the wake-word gate, so this doesn't change book-game
# answer accuracy live, but it's the correct plumbing for whenever that
# file gets a broader consumer, and it does matter immediately if a real
# wake-word mishear variant ever repeats.
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
# finding), and crt-book-console.py now reads its own stdin for exactly
# this reason. Making `book` the boot default is the code-level half of
# that fix (a manual `tmux select-window` was done live but didn't
# survive a respawn/reboot) -- `claude` stays one `prefix+0` away, and
# voice/STT already covers claude-facing interaction without needing
# window 0's focus.
# Boot-default window. In the idle-lean layout the screensaver (window 0)
# IS the idle face, so select it. Otherwise keep `book` as the default
# (the 2026-07-21 scanner-keystroke-focus decision above) -- `claude`/
# screensaver stays one prefix+0 away either way.
if [ "${CRT_NO_IDLE_CLAUDE:-0}" = "1" ]; then
  tmux select-window -t "${SESSION}:0"
else
  tmux select-window -t "${SESSION}:book"
fi
exec tmux attach -t "$SESSION"
