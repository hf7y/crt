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
    ' _ "$input" 2>/dev/null | grep -oE '\[hookswitch\] (on|off)-hook$' \
    | sed -e 's/.*\[hookswitch\] //' -e 's/-hook//' \
    | paste -sd, -
}
# The committed TRANSITION is what these cases are about, and it is now the
# only thing printed unconditionally. Until 2026-07-25 they matched
# "on-hook -> pausing STT" -- a sentence the script printed before running
# the pkill and without checking it, against a process name nothing has run
# since 2026-07-20. Matching on it meant this file could only pass while
# that claim stayed unverified. See TheClaimAboutSTT cases at the bottom.

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
# rapid chatter.
run_spaced_case() {
  # No wall-clock budget: the feeder holds the pipe open until both commits
  # are SEEN (10s ceiling), so load makes this slower, never red (crt#30).
  local out; out="$(mktemp)"
  CRT_HOOK_TEST_MODE=1 CRT_HOOK_DEBOUNCE_MS=30 CRT_HOOK_KEY=KEY_F13 \
    bash -c '
      source "'"$BIN_DIR"'/hookswitch-listen.sh"
      { echo "'"$line_on"'"; sleep 0.1; echo "'"$line_off"'"; sleep 30; } | debounce_loop &
      pid=$!
      for _ in $(seq 100); do
        [ "$(grep -c "\[hookswitch\] \(on\|off\)-hook$" "'"$out"'" 2>/dev/null)" -ge 2 ] && break
        sleep 0.1
      done
      kill "$pid" 2>/dev/null
      wait "$pid" 2>/dev/null
    ' >"$out" 2>/dev/null
  grep -oE '\[hookswitch\] (on|off)-hook$' "$out" \
    | sed -e 's/.*\[hookswitch\] //' -e 's/-hook//' \
    | paste -sd, -
}
got=$(run_spaced_case)
check "two real, separated transitions both commit" "on,off" "$got"

# --- what it says about STT, which it never used to check -----------------
#
# apply_state announced "pausing STT" before running the pkill and threw
# the result away (`2>/dev/null || true`). crt-console.sh has not run
# stt-feed.sh since 2026-07-20 -- the sole-mic-reader layout replaced it --
# so on potato that pkill matches nothing and the console has been claiming
# a pause it did not perform every time the handset moved.
run_apply_state() {  # $1 = on|off, $2 = process pattern. prints stdout+stderr
  CRT_HOOK_TEST_MODE=1 CRT_HOOK_STT_PROCESS="$2" \
    CRT_THOUGHT_LOG="$THOUGHTS" bash -c '
      source "'"$BIN_DIR"'/hookswitch-listen.sh"
      apply_state "'"$1"'"
    ' 2>&1
}

THOUGHTS="$(mktemp -d)/thoughts.log"

# Nothing on any box is called this, which is the live case on potato.
out="$(run_apply_state on "no-such-process-anywhere-$$")"
case "$out" in
  *"[hookswitch] on-hook"*"STT NOT paused"*"no process matches"*)
    echo "ok - a pause that paused nothing says so, and names what it looked for" ;;
  *)
    echo "FAIL - apply_state still claims a pause it did not perform: [$out]"
    fail=1 ;;
esac
if grep -q "carried on listening anyway" "$THOUGHTS" 2>/dev/null; then
  echo "ok - the unperformed pause reaches window 1, not just stderr"
else
  echo "FAIL - nothing about the unperformed pause reached the thought log"
  fail=1
fi

# And the honest positive: a process that DOES exist gets signalled and
# reported as signalled. A sleep of our own, resumed rather than paused, so
# a stray SIGSTOP cannot leave anything wedged if this test is interrupted.
sleep 30 &
victim=$!
out="$(run_apply_state off "sleep 30")"
kill "$victim" 2>/dev/null
wait "$victim" 2>/dev/null
case "$out" in
  *"[hookswitch] off-hook"*"STT resumed (SIGCONT -> sleep 30)"*)
    echo "ok - a signal that landed is reported as landed, with the signal named" ;;
  *)
    echo "FAIL - a successful resume was not reported correctly: [$out]"
    fail=1 ;;
esac

exit "$fail"
