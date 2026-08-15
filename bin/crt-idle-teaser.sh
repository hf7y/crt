#!/usr/bin/env bash
# Watches ~/reports/crt/LATEST.md (crt-report.sh, or eventually the
# nightly batch) and an optional open-questions file (CRT_QUESTIONS_FILE,
# unset by default -- see below) for new entries, and turns each
# new one into exactly one first-person teaser line on screen (via
# crt-think.sh -> crt-monologue.sh) plus, for genuine judgment calls only,
# one earcon -- see IDLE-BAIT.md for the full design and why this is
# deliberately NOT a repeating notification.
#
# Deliberately a separate watcher rather than baked into crt-monologue.sh
# itself -- see PHILOSOPHY.md's open thread on whether always-on narration
# already competes for the same scarce attention idle-bait needs; keeping
# this additive and optional means that tension can be resolved later
# without touching the base monologue.
#
# STATUS: NOT hardware-verified -- polling loop and hashing logic are
# correct as designed but never run against live report/question traffic.
#
# Usage: crt-idle-teaser.sh   (run as its own tmux pane/background loop)
set -uo pipefail
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

REPORTS_DIR="${CRT_REPORTS_DIR:-$HOME/reports/crt}"
REPO_DIR="${CRT_REPO_DIR:-$HOME/crt}"
# No default: the repo-local questions file this used to watch was retired by
# scheduler#66 in favour of GitHub issues and deleted by realisateur#293.
# Unset = reports-only, and the question earcon never fires. Wiring this back
# onto the issue tracker is crt#40.
QUESTIONS="${CRT_QUESTIONS_FILE:-}"
SEEN="${CRT_IDLE_SEEN:-$HOME/.crt/idle-bait.seen}"
POLL_SECS="${CRT_IDLE_POLL:-30}"
ANNOUNCE_LOCK="${CRT_ANNOUNCE_LOCK:-$HOME/.crt/announce.lastrun}"
ANNOUNCE_MIN_GAP="${CRT_ANNOUNCE_MIN_GAP:-900}"

# Idle timeout (2026-07-19, replaces an earlier "quiet hours" clock-window
# idea per Chris: "like a screensaver... a combination of low handset
# volume and other markers going idle"). The WHOLE idle-bait mechanism --
# teaser line AND chime, not just audio -- only activates once the room's
# been quiet for a while, the way a screensaver only appears after
# inactivity. See IDLE-BAIT.md for the full writeup.
#
# "Activity" = the newest mtime across CRT_IDLE_MARKERS: today that's just
# ~/.crt/stt.log (someone spoke) and ~/.crt/sideband.state (a state
# transition happened, SIDEBAND.md) -- both already exist/get touched by
# other pieces of this project. ~/.crt/mic-level is a placeholder for a
# future marker (a raw peak-level ping from crt-stt-solo.py even below the
# VAD utterance threshold, i.e. "someone's near the phone" without having
# said anything yet) -- nothing writes it yet, harmless to list since a
# missing marker file just doesn't count toward "recent."
IDLE_TIMEOUT_SECS="${CRT_IDLE_TIMEOUT_SECS:-1200}"   # 20min, first guess, tune once live
IDLE_MARKERS="${CRT_IDLE_MARKERS:-$HOME/.crt/stt.log $HOME/.crt/mic-level $HOME/.crt/sideband.state}"

mkdir -p "$(dirname "$SEEN")"
touch "$SEEN"

last_activity_epoch() {
  local newest=0 f mtime
  for f in $IDLE_MARKERS; do
    [ -f "$f" ] || continue
    mtime=$(stat -c %Y "$f" 2>/dev/null || echo 0)
    [ "$mtime" -gt "$newest" ] && newest="$mtime"
  done
  echo "$newest"
}

is_idle() {
  local now last elapsed
  now=$(date +%s)
  last=$(last_activity_epoch)
  elapsed=$(( now - last ))
  [ "$elapsed" -ge "$IDLE_TIMEOUT_SECS" ]
}

already_seen() {
  grep -qxF "$1" "$SEEN" 2>/dev/null
}

mark_seen() {
  echo "$1" >> "$SEEN"
}

can_chime() {
  local now last elapsed
  now=$(date +%s)
  last=0
  [ -f "$ANNOUNCE_LOCK" ] && last=$(cat "$ANNOUNCE_LOCK" 2>/dev/null || echo 0)
  elapsed=$(( now - last ))
  [ "$elapsed" -ge "$ANNOUNCE_MIN_GAP" ]
}

chime() {
  # $1 = bait|question -- shares crt-announce.sh's lockfile so a chime and
  # a TV announcement can never stack (IDLE-BAIT.md's single-rate-limit rule).
  #
  # 2026-07-25: this was `crt-earcon.sh "$1" >/dev/null 2>&1 || true` with
  # the stamp written first and never taken back, which is two of this
  # project's own recurring bugs in three lines.
  #
  #   - The earcon's failure went to /dev/null and then to `|| true`. sox
  #     missing, a device that will not open, a name this script and that
  #     one disagree about -- all identical to a chime that played. Same
  #     class as cdf05cc's silent earcon and f187a45's discarded exit
  #     status; the fix is the same one, say what it said on its way out.
  #   - The stamp was spent whether or not anything was heard, and the
  #     window is SHARED with crt-announce.sh's TV voice. So an earcon that
  #     cannot play would also mute working TV announcements for fifteen
  #     minutes at a time, which is a fault spreading between channels, not
  #     a rate limit.
  #
  # Stamp first (a concurrent chime must still be blocked while this one is
  # attempting), roll back if nothing played. No retry storm: the caller
  # mark_seen()s each line before chiming, so a failing chime is retried at
  # most once per new report/question line, not once per poll.
  local prev had_lock=0 err status=0
  can_chime || return 0
  if [ -f "$ANNOUNCE_LOCK" ]; then
    had_lock=1
    prev="$(cat "$ANNOUNCE_LOCK" 2>/dev/null || echo 0)"
  fi
  date +%s > "$ANNOUNCE_LOCK"

  err="$("$BIN_DIR/crt-earcon.sh" "$1" 2>&1 >/dev/null)" || status=$?
  [ "$status" = 0 ] && return 0

  if [ "$had_lock" = 1 ]; then
    printf '%s\n' "$prev" > "$ANNOUNCE_LOCK"
  else
    rm -f "$ANNOUNCE_LOCK"
  fi
  # Last non-blank line of whatever it complained about -- crt-earcon.sh
  # prefixes its own messages ("[crt-earcon] sox not installed").
  err="$(printf '%s\n' "$err" | grep -v '^[[:space:]]*$' | tail -1)"
  echo "[crt-idle-teaser] chime '$1' did not play (exit $status): ${err:-no output}" >&2
  "$BIN_DIR/crt-think.sh" "meant to make a noise just then. nothing came out: ${err:-silence}" 2>/dev/null || true
  return 0
}

# ANSI color-per-register (2026-07-20, EXPRESSIVE-TONE.md's color
# dimension, named but not reached until now): each teaser kind gets a
# color matching its register in that doc's table -- clipped/urgent
# (blocker) reads bold magenta, a real question reads yellow (present, not
# alarming), an ordinary find reads the same cyan "warm/curious" register
# as the `curious`/`bait` earcons. crt-think.sh just appends whatever text
# it's given, so the color codes ride along into thoughts.log and
# crt-monologue.sh's tail+fold displays them as-is -- terminals interpret
# ANSI codes regardless of exactly where fold's byte-counting wraps, so
# this works even though fold (correctly) doesn't know the escape bytes
# are zero-width; given how short these teaser lines are, in practice
# that just doesn't come up.
#
# CRT-SAFE PALETTE (2026-07-25): this was `1;31` (bold red) from the day it
# was written, which CLAUDE.md and BOOK-GAME-STYLE.md both name as banned
# outright -- 31/32/34 and 91/92/94 bleed and smear on a real composite/RF
# tube at any boldness. The book-game palette was reassigned for exactly
# this on 2026-07-21 and this file was missed, so the ONE teaser register
# most likely to be worth reading (a blocker) was the one drawn in the
# worst color the tube has. Magenta is where that doc's corrected table
# already puts the clipped register (`COLOR_WRONG`); bold carries the
# urgency red was doing. Enforced repo-wide now, not just for the book
# game's palette: tests/test_crt_safe_colors.sh.
COLOR_URGENT=$'\033[1;35m'    # blocker (clipped register, CRT-safe)
COLOR_QUESTION=$'\033[33m'    # a real judgment call
COLOR_CURIOUS=$'\033[36m'     # ordinary find
COLOR_RESET=$'\033[0m'

color_for_line() {
  local line="$1"
  case "$line" in
    *BLOCKER*|*blocker*) printf '%s' "$COLOR_URGENT" ;;
    *QUESTION*|*question*|*'> (answer'*) printf '%s' "$COLOR_QUESTION" ;;
    *) printf '%s' "$COLOR_CURIOUS" ;;
  esac
}

teaser_for_line() {
  # $1 = the raw report/question line. Turn it into a short curious
  # first-person hook rather than echoing the line verbatim -- verbatim
  # status text is exactly the "nag" framing IDLE-BAIT.md is against.
  local line="$1"
  case "$line" in
    *BLOCKER*|*blocker*)
      echo "hit a snag on something. kind of a funny one. ask me what's up?" ;;
    *QUESTION*|*question*|*'> (answer'*)
      echo "i've got a real question for you, whenever you pick up." ;;
    *)
      echo "found something while you were gone. wanna hear?" ;;
  esac
}

process_new_lines() {
  local file="$1" kind="$2"  # kind: report | question
  [ -f "$file" ] || return 0
  while IFS= read -r line; do
    case "$line" in
      "- "*) ;;   # only bullet lines are real entries, same convention the reports use
      *) continue ;;
    esac
    local h
    h="$(printf '%s' "$line" | sha1sum | cut -d' ' -f1)"
    already_seen "$h" && continue
    mark_seen "$h"

    teaser="$(teaser_for_line "$line")"
    color="$(color_for_line "$line")"
    "$BIN_DIR/crt-think.sh" "${color}${teaser}${COLOR_RESET}"

    if [ "$kind" = "question" ]; then
      chime question
    else
      case "$line" in
        *BLOCKER*|*blocker*) chime bait ;;
        *) : ;;  # plain informational notes get NO audio, see IDLE-BAIT.md
      esac
    fi
  done < "$file"
}

# Guarded so tests/test_idle_teaser.sh can source this file (to reuse
# is_idle/last_activity_epoch/process_new_lines) without starting the
# real infinite poll loop.
if [ "${CRT_IDLE_TEASER_TEST_MODE:-0}" = "0" ]; then
  echo "[crt-idle-teaser] watching $REPORTS_DIR/LATEST.md + $QUESTIONS (poll ${POLL_SECS}s, idle timeout ${IDLE_TIMEOUT_SECS}s)" >&2

  while true; do
    # Screensaver-style: while the room's been active recently, don't even
    # look for new items to tease -- anything that shows up gets left
    # unmarked (not "seen" yet) so it's picked up the moment is_idle()
    # flips true, rather than being missed or requiring a separate queue.
    if is_idle; then
      process_new_lines "$REPORTS_DIR/LATEST.md" report
      process_new_lines "$QUESTIONS" question
    fi
    sleep "$POLL_SECS"
  done
fi
