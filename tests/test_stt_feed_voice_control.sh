#!/usr/bin/env bash
# Offline test for stt-feed.sh's voice_control_keystroke() -- the
# single-word "yes"/"no"/"up"/"down"/"clear" -> tmux-keystroke mapping.
# Can't source the real script (unconditional mixer/tmux-wait side effects
# at the top, same reason the gate/secretary flag tests don't either) --
# extracts the function verbatim, same pattern as those two tests.
#
# This function used to read a bare $key that nothing in its scope set (a
# `local key` inside a *different* function, out of scope by the time this
# code ran) -- harmless under normal bash, but fatal under stt-feed.sh's own
# `set -u`: the very first single-word utterance (a plain "yes" or "no")
# threw "unbound variable" and killed the whole capture loop. Confirmed here
# by running under `set -u` too, not just checking the match logic.
set -uo pipefail
fail=0
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)"

eval "$(sed -n '/^voice_control_keystroke() {/,/^}/p' "$BIN_DIR/stt-feed.sh")"

check() {
  local desc="$1" expected="$2" got="$3"
  if [ "$got" = "$expected" ]; then
    echo "ok - $desc"
  else
    echo "FAIL - $desc: expected [$expected], got [$got]"
    fail=1
  fi
}

keystroke_for() {
  set -u
  voice_control_keystroke "$1" 2>/dev/null || echo "(no match)"
}

check "'yes' maps to Enter" "Enter" "$(keystroke_for "yes")"
check "'Yes!' (mixed case, punctuation) still maps to Enter" "Enter" "$(keystroke_for "Yes!")"
check "'ok' maps to Enter" "Enter" "$(keystroke_for "ok")"
check "'no' maps to Escape" "Escape" "$(keystroke_for "no")"
check "'nevermind' maps to Escape" "Escape" "$(keystroke_for "nevermind")"
check "'up' maps to Up" "Up" "$(keystroke_for "up")"
check "'down' maps to Down" "Down" "$(keystroke_for "down")"
check "'clear' maps to C-u" "C-u" "$(keystroke_for "clear")"
check "an unrecognized single word matches nothing" "(no match)" "$(keystroke_for "banana")"

# The actual regression: this used to reference an out-of-scope $key and
# die with "unbound variable" under set -u the moment it ran for real.
if (set -u; voice_control_keystroke "yes" >/dev/null); then
  echo "ok - voice_control_keystroke runs clean under set -u (was: unbound variable)"
else
  echo "FAIL - voice_control_keystroke still errors under set -u"
  fail=1
fi

# The call site itself: confirm the main loop calls the function (passing
# $text as a real argument) rather than inlining its own case on a bare
# $key, so a regression back to that shape is caught here too.
if grep -q 'voice_control_keystroke "\$text"' "$BIN_DIR/stt-feed.sh"; then
  echo "ok - stt-feed.sh's main loop calls voice_control_keystroke with \$text"
else
  echo "FAIL - stt-feed.sh's main loop no longer calls voice_control_keystroke"
  fail=1
fi

exit "$fail"
