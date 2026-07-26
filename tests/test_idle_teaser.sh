#!/usr/bin/env bash
# Offline tests for crt-idle-teaser.sh's screensaver-style idle detection
# (is_idle/last_activity_epoch) -- controls marker file mtimes directly via
# `touch -d`, no real mic/STT activity needed.
set -uo pipefail
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)"
fail=0

check() {
  local desc="$1" expected="$2" got="$3"
  if [ "$got" = "$expected" ]; then
    echo "ok - $desc"
  else
    echo "FAIL - $desc: expected [$expected], got [$got]"
    fail=1
  fi
}

TMPDIR="$(mktemp -d)"
FAKE_BIN="$(mktemp -d)"
trap 'rm -rf "$TMPDIR" "$FAKE_BIN"' EXIT

# This file reaches the LIVE console through two doors, both found
# 2026-07-25 by run_tests.sh's live-state guard and by reading what it
# actually runs. Neither is about what is under test here.
#
#  1. `chime` stamps CRT_ANNOUNCE_LOCK -- default ~/.crt/announce.lastrun,
#     the 15-minute rate limit SHARED with crt-announce.sh's TV
#     announcements (IDLE-BAIT.md's single-rate-limit rule). Running the
#     suite on potato therefore bought the console fifteen minutes of
#     silence: the next real bait chime AND the next real TV announcement
#     both suppressed, for no reason anyone could have traced.
#  2. `chime` then execs the real bin/crt-earcon.sh, which on a box with
#     sox installed ends in `aplay -D default` -- the suite makes the
#     console beep. The guard cannot ever catch that one; sound is not a
#     file. Faked on PATH the same way test_earcon_capture_duck.sh and
#     test_earcon_sideband_duck.sh already do.
#
# CRT_IDLE_SEEN is pinned too: this script `touch`es it at SOURCE time, so
# every case below (not just the two that tease) reached the live
# ~/.crt/idle-bait.seen ledger.
export CRT_ANNOUNCE_LOCK="$TMPDIR/announce.lastrun"
export CRT_IDLE_SEEN="$TMPDIR/seen.default"
cat > "$FAKE_BIN/aplay" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
cat > "$FAKE_BIN/sox" <<'EOF'
#!/usr/bin/env bash
for a in "$@"; do
  case "$a" in *.wav) : > "$a" ;; esac
done
exit 0
EOF
chmod +x "$FAKE_BIN/aplay" "$FAKE_BIN/sox"
export PATH="$FAKE_BIN:$PATH"

run_is_idle() {
  # $1 = marker file paths (space-separated), $2 = timeout secs
  CRT_IDLE_TEASER_TEST_MODE=1 CRT_IDLE_MARKERS="$1" CRT_IDLE_TIMEOUT_SECS="$2" \
    bash -c '
      source "'"$BIN_DIR"'/crt-idle-teaser.sh"
      if is_idle; then echo idle; else echo active; fi
    '
}

# Case 1: no marker files exist at all -> nothing recent -> idle.
check "no markers at all -> idle" "idle" "$(run_is_idle "$TMPDIR/nope1 $TMPDIR/nope2" 60)"

# Case 2: a marker touched just now, timeout is long -> active.
recent="$TMPDIR/recent"
touch "$recent"
check "recently touched marker -> active" "active" "$(run_is_idle "$recent" 3600)"

# Case 3: a marker touched long ago (mocked via touch -d), short timeout -> idle.
old="$TMPDIR/old"
touch -d "2020-01-01" "$old"
check "old marker, short timeout -> idle" "idle" "$(run_is_idle "$old" 60)"

# Case 4: multiple markers -- the NEWEST one wins (one recent, one old).
touch "$TMPDIR/old2" -d "2020-01-01"
touch "$TMPDIR/recent2"
check "newest marker among several wins -> active" "active" \
  "$(run_is_idle "$TMPDIR/old2 $TMPDIR/recent2" 3600)"

# Case 5: process_new_lines is skipped entirely while active (screensaver
# gate) -- a fresh report line should NOT produce a teaser/chime yet.
report_file="$TMPDIR/LATEST.md"
echo "- **09:00 (note):** something happened" > "$report_file"
touch "$TMPDIR/active_marker"   # forces active
out=$(CRT_IDLE_TEASER_TEST_MODE=1 CRT_IDLE_MARKERS="$TMPDIR/active_marker" \
      CRT_IDLE_TIMEOUT_SECS=3600 CRT_IDLE_SEEN="$TMPDIR/seen1" \
      CRT_THOUGHT_LOG="$TMPDIR/thoughts.log" \
      bash -c '
        source "'"$BIN_DIR"'/crt-idle-teaser.sh"
        if is_idle; then
          process_new_lines "'"$report_file"'" report
        fi
      ' 2>&1)
if [ -f "$TMPDIR/thoughts.log" ]; then
  echo "FAIL - active room: teaser fired when it should have waited for idle"
  fail=1
else
  echo "ok - active room: no teaser fires while active"
fi

# --- ANSI color-per-register (EXPRESSIVE-TONE.md) ---
run_color_for_line() {
  CRT_IDLE_TEASER_TEST_MODE=1 bash -c '
    source "'"$BIN_DIR"'/crt-idle-teaser.sh"
    color_for_line "'"$1"'"
  '
}

COLOR_URGENT_EXPECTED=$'\033[1;31m'
got="$(run_color_for_line "- **09:00 (BLOCKER):** something broke")"
check "blocker line -> urgent red" "$COLOR_URGENT_EXPECTED" "$got"

COLOR_QUESTION_EXPECTED=$'\033[33m'
got="$(run_color_for_line "- **09:00 (QUESTION):** pick one")"
check "question line -> yellow" "$COLOR_QUESTION_EXPECTED" "$got"

COLOR_CURIOUS_EXPECTED=$'\033[36m'
got="$(run_color_for_line "- **09:00 (note):** just fyi")"
check "plain note -> curious cyan" "$COLOR_CURIOUS_EXPECTED" "$got"

# End-to-end: a colored teaser actually lands in thoughts.log wrapped in
# the color + a reset code, once idle.
report_file2="$TMPDIR/LATEST2.md"
echo "- **09:00 (BLOCKER):** something broke" > "$report_file2"
touch -d "2020-01-01" "$TMPDIR/old_marker"
CRT_IDLE_TEASER_TEST_MODE=1 CRT_IDLE_MARKERS="$TMPDIR/old_marker" \
  CRT_IDLE_TIMEOUT_SECS=60 CRT_IDLE_SEEN="$TMPDIR/seen2" \
  CRT_THOUGHT_LOG="$TMPDIR/thoughts2.log" \
  bash -c '
    source "'"$BIN_DIR"'/crt-idle-teaser.sh"
    if is_idle; then
      process_new_lines "'"$report_file2"'" report
    fi
  ' >/dev/null 2>&1
if grep -qF "$COLOR_URGENT_EXPECTED" "$TMPDIR/thoughts2.log" 2>/dev/null && \
   grep -qF $'\033[0m' "$TMPDIR/thoughts2.log" 2>/dev/null; then
  echo "ok - colored teaser reaches thoughts.log with color + reset"
else
  echo "FAIL - colored teaser missing color/reset codes in thoughts.log"
  fail=1
fi

# That case is a BLOCKER, so it chimed -- which is the whole reason the
# lock is pinned above. Assert the stamp landed in the PINNED file rather
# than only asserting the live one is untouched: a pin that silently stops
# working looks exactly like a chime that never fired.
if [ -s "$CRT_ANNOUNCE_LOCK" ] && grep -qE '^[0-9]+$' "$CRT_ANNOUNCE_LOCK"; then
  echo "ok - the chime's rate-limit stamp went to the pinned lock, not ~/.crt"
else
  echo "FAIL - no epoch stamp in the pinned announce lock ($CRT_ANNOUNCE_LOCK)"
  fail=1
fi

# And the shared rate limit is honoured: a second blocker inside
# CRT_ANNOUNCE_MIN_GAP must NOT re-chime. This is IDLE-BAIT.md's rule that
# a chime and a TV announcement can never stack, and nothing tested it.
stamp_before="$(cat "$CRT_ANNOUNCE_LOCK")"
echo "1" > "$CRT_ANNOUNCE_LOCK"        # epoch 1970: gap long past -> may chime
CRT_IDLE_TEASER_TEST_MODE=1 bash -c '
  source "'"$BIN_DIR"'/crt-idle-teaser.sh"
  if can_chime; then echo yes; else echo no; fi
' > "$TMPDIR/canchime_old"
check "a long-expired lock permits a chime" "yes" "$(cat "$TMPDIR/canchime_old")"

echo "$stamp_before" > "$CRT_ANNOUNCE_LOCK"   # stamped just now -> must not
CRT_IDLE_TEASER_TEST_MODE=1 bash -c '
  source "'"$BIN_DIR"'/crt-idle-teaser.sh"
  if can_chime; then echo yes; else echo no; fi
' > "$TMPDIR/canchime_fresh"
check "a fresh lock suppresses the next chime" "no" "$(cat "$TMPDIR/canchime_fresh")"

exit "$fail"
