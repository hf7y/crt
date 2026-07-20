#!/usr/bin/env bash
# Offline test for hookswitch-listen.sh's debounce logic (HOOKSWITCH.md) --
# feeds synthetic raw evtest-shaped lines through the real debounce_loop/
# apply_state functions, no physical switch needed.
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

line_off="Event: type 1 (EV_KEY), code 1 (KEY_F13), value 0"
line_on="Event: type 1 (EV_KEY), code 1 (KEY_F13), value 1"

run_case() {
  # $1 = the raw lines to feed, all delivered immediately (bounce-shaped);
  # the feeder then holds the pipe open past the debounce window (like the
  # real evtest stream, which never EOFs) so debounce_loop actually gets to
  # commit, then is killed. prints apply_state's actions, comma-joined.
  local input="$1"
  CRT_HOOK_TEST_MODE=1 CRT_HOOK_DEBOUNCE_MS=30 CRT_HOOK_KEY=KEY_F13 \
    bash -c '
      source "'"$BIN_DIR"'/hookswitch-listen.sh"
      { printf "%s" "$1"; sleep 1; } | debounce_loop &
      pid=$!
      sleep 0.15
      kill "$pid" 2>/dev/null
      wait "$pid" 2>/dev/null
    ' _ "$input" 2>/dev/null | grep -oE 'on-hook -> pausing STT|off-hook -> resuming STT' \
    | sed -e 's/on-hook -> pausing STT/on/' -e 's/off-hook -> resuming STT/off/' \
    | paste -sd, -
}

# Case 1: a clean single transition (lift the handset) -> exactly one "off".
got=$(run_case "$line_off"$'\n')
check "single clean transition commits once" "off" "$got"

# Case 2: a bounce train (value 0, 1, 0, 1, 0, all delivered together with
# no real gap) should collapse to exactly the FINAL settled state, not one
# action per bounce. Built without $(...) -- command substitution strips
# trailing newlines, which would silently drop the final "off" event and
# make this test pass or fail for the wrong reason.
bounce="$line_off"$'\n'"$line_on"$'\n'"$line_off"$'\n'"$line_on"$'\n'"$line_off"$'\n'
got=$(run_case "$bounce")
check "bounce train collapses to one final action" "off" "$got"

# Case 3: two genuinely separate transitions (separated by more than the
# debounce window) both commit -- debounce must not eat real events, only
# rapid chatter. Use `sleep` between writes via a background feeder so the
# gap is real wall-clock time, not just line order.
run_spaced_case() {
  CRT_HOOK_TEST_MODE=1 CRT_HOOK_DEBOUNCE_MS=30 CRT_HOOK_KEY=KEY_F13 \
    bash -c '
      source "'"$BIN_DIR"'/hookswitch-listen.sh"
      { echo "'"$line_on"'"; sleep 0.1; echo "'"$line_off"'"; sleep 0.1; } | debounce_loop &
      pid=$!
      sleep 0.35
      kill "$pid" 2>/dev/null
      wait "$pid" 2>/dev/null
    ' 2>/dev/null | grep -oE 'on-hook -> pausing STT|off-hook -> resuming STT' \
    | sed -e 's/on-hook -> pausing STT/on/' -e 's/off-hook -> resuming STT/off/' \
    | paste -sd, -
}
got=$(run_spaced_case)
check "two real, separated transitions both commit" "on,off" "$got"

exit "$fail"
