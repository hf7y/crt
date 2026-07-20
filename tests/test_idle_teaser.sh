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
trap 'rm -rf "$TMPDIR"' EXIT

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

exit "$fail"
