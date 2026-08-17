#!/usr/bin/env bash
# The CRT-safe palette rule, enforced across EVERY file that draws on the
# tube -- not just one program's palette constants.
#
# HARD RULE (CLAUDE.md; BOOK-GAME-STYLE.md's color section, updated
#   [rest: vault:crt/header-archaeology-20260817.md]
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$DIR/.." && pwd)"
fail=0

# An ANSI SGR sequence written any of the four ways this repo writes them
# ($'\033[..m' in shell, "\033[..m"/"\x1b[..m" in Python, or a literal ESC
# byte), whose parameter list contains a banned code as a WHOLE parameter:
# `1;31` and `31` fire, `131` and `3` do not. The leading `([0-9]+;)*`
#   [rest: vault:crt/header-archaeology-20260817.md]
BANNED='31|32|34|91|92|94'
PATTERN='(\\033|\\x1b|\\e|'$'\x1b'')\[([0-9]+;)*(?<!;5;)('"$BANNED"')(;[0-9]+)*m'
GREP=(grep -P)

# This file necessarily names the banned codes in its own pattern and
# prose, so it is the one exclusion. Everything else is fair game.
# This file necessarily names the banned codes in its own pattern and
# prose. Other files that must quote a banned sequence VERBATIM (a test
# proving a detector catches it -- tests/test_screensaver.py) mark the
# line with the opt-out below; it has to be typed deliberately, per line,
# so a real violation can never inherit it from a neighbour.
ALLOW_MARKER='crt-safe-colors: verbatim'
hits="$("${GREP[@]}" -rn "$PATTERN" "$REPO/bin" "$REPO/tests" 2>/dev/null \
        | grep -v "^$REPO/tests/test_crt_safe_colors.sh:" \
        | grep -vF "$ALLOW_MARKER")"

if [ -n "$hits" ]; then
  echo "FAIL - banned primary-RGB ANSI codes reach the CRT (see CLAUDE.md):"
  printf '%s\n' "$hits" | sed 's/^/    /'
  fail=1
else
  echo "ok - no banned primary-RGB ANSI codes in bin/ or tests/"
fi

# ...and prove the check can actually fail, because a grep that matches
# nothing looks identical to a grep that is broken. Same reasoning as the
# manifest check in run_tests.sh: an assertion nobody has seen go red is
# not yet an assertion.
probe="$(mktemp -d)"
trap 'rm -rf "$probe"' EXIT
printf 'COLOR_URGENT=$%s\n' "'\\033[1;31m'" > "$probe/decoy.sh"
printf 'C = "\\x1b[92m"\n' > "$probe/decoy.py"
found="$("${GREP[@]}" -rl "$PATTERN" "$probe" 2>/dev/null | wc -l)"
if [ "$found" = "2" ]; then
  echo "ok - the check detects a banned code in both shell and python spelling"
else
  echo "FAIL - self-probe: expected 2 decoy files flagged, got $found"
  fail=1
fi

# The safe half of the palette must NOT trip it -- a rule that flags
# yellow/magenta/cyan/white would just get switched off.
printf 'C = "\\033[1;35m"\nD = $%s\nE = "\\x1b[2;36m"\nF = "\\033[37m"\nG = "\\033[33m"\n' \
  "'\\033[0m'" > "$probe/safe.py"
if "${GREP[@]}" -q "$PATTERN" "$probe/safe.py" 2>/dev/null; then
  echo "FAIL - self-probe: the CRT-safe palette itself was flagged"
  fail=1
else
  echo "ok - yellow/magenta/cyan/white/reset are not flagged"
fi

# 131 is not 31 and 3 is not 31: a substring match would call both red.
# 231 and 341 are the same trap from the other end (a banned code sitting
# at the START of a longer number), and `2;33` proves a multi-parameter
# sequence is still read parameter by parameter.
printf 'A = "\\033[131m"\nB = "\\033[3m"\nC = "\\033[231m"\nD = "\\033[341m"\nE = "\\033[2;33m"\n' \
  > "$probe/nearmiss.py"
if "${GREP[@]}" -q "$PATTERN" "$probe/nearmiss.py" 2>/dev/null; then
  echo "FAIL - self-probe: matched a number that merely contains a banned code"
  fail=1
else
  echo "ok - does not fire on numbers that merely contain a banned code"
fi

# The 256-color exclusion, both directions -- an exclusion that
# nobody has watched work is the same unwatched assertion as above. A
# palette index that happens to read 94 must pass; a real bright-blue
# sitting next to one must still fire.
printf 'A = "\\x1b[38;5;94m"\nB = "\\x1b[48;5;31m"\nC = "\\033[1;38;5;92m"\n' \
  > "$probe/palette256.py"
if "${GREP[@]}" -q "$PATTERN" "$probe/palette256.py" 2>/dev/null; then
  echo "FAIL - self-probe: a 256-color palette index was read as an SGR color"
  fail=1
else
  echo "ok - 256-color palette indices are not mistaken for primaries"
fi

printf 'A = "\\x1b[38;5;94m"\nB = "\\x1b[94m"\n' > "$probe/mixed.py"
if "${GREP[@]}" -q "$PATTERN" "$probe/mixed.py" 2>/dev/null; then
  echo "ok - a real banned code still fires alongside a 256-color sequence"
else
  echo "FAIL - self-probe: the exclusion swallowed a real banned code"
  fail=1
fi

exit "$fail"
