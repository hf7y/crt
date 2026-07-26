#!/usr/bin/env bash
# The CRT-safe palette rule, enforced across EVERY file that draws on the
# tube -- not just one program's palette constants.
#
# HARD RULE (CLAUDE.md; BOOK-GAME-STYLE.md's color section, updated
# 2026-07-21 by Zach and confirmed live on the real tube): this is a real
# analog CRT over composite/RF, so chroma bandwidth is far below luma and
# saturated primaries bleed/smear/ring. Never ANSI 31, 32, 34 (standard
# red/green/blue) or 91, 92, 94 (their bright variants), at ANY
# boldness/dimness. Only 33 (yellow), 35 (magenta), 36 (cyan) and 37
# (white), plus dim/bold modifiers on those.
#
# WHY THIS FILE EXISTS (2026-07-25). That rule already had mechanical
# enforcement -- `tests/test_book_game.py`'s
# `test_no_primary_rgb_codes_in_palette`, which CLAUDE.md cites by name as
# the proof it is "not just a comment". But it checks five named constants
# inside one Python module. `bin/crt-idle-teaser.sh` had carried
# `COLOR_URGENT=$'\033[1;31m'` since the day it was written, straight onto
# window 1 via crt-think.sh -> thoughts.log, and no test could see it: the
# book game's palette was reassigned to comply on 2026-07-21 and this file
# was simply missed. An enforcement that only covers the place someone
# already thought about is the same silent-pass class this project keeps
# finding elsewhere -- so this one reads the files.
#
# Scope: bin/ (everything that renders to the tube) plus tests/, because a
# test asserting a banned code is how a violation gets pinned in place --
# which is exactly what happened here (test_idle_teaser.sh asserted the red
# it was supposed to catch). Deliberately a plain grep over source text
# rather than an import: half of bin/ is shell, and the point is to cover
# every file regardless of language.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$DIR/.." && pwd)"
fail=0

# An ANSI SGR sequence written any of the four ways this repo writes them
# ($'\033[..m' in shell, "\033[..m"/"\x1b[..m" in Python, or a literal ESC
# byte), whose parameter list contains a banned code as a WHOLE parameter:
# `1;31` and `31` fire, `131` and `3` do not. The leading `([0-9]+;)*`
# insists every earlier parameter ends at a semicolon, which is what makes
# 131 a near miss rather than a hit.
#
# Known and accepted over-match: a 256-color `\033[38;5;31m` (palette index
# 31, not red at all) would trip this. Nothing in this repo uses 256-color
# sequences and the tube would not render them predictably anyway, so the
# cheap loud false positive is the better trade -- it costs one line of
# explanation if it ever happens; the opposite error is the bug that put
# bold red on the tube for five days.
BANNED='31|32|34|91|92|94'
PATTERN='(\\033|\\x1b|\\e|'$'\x1b'')\[([0-9]+;)*('"$BANNED"')(;[0-9]+)*m'

# This file necessarily names the banned codes in its own pattern and
# prose, so it is the one exclusion. Everything else is fair game.
hits="$(grep -rnE "$PATTERN" "$REPO/bin" "$REPO/tests" 2>/dev/null \
        | grep -v "^$REPO/tests/test_crt_safe_colors.sh:")"

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
found="$(grep -rlE "$PATTERN" "$probe" 2>/dev/null | wc -l)"
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
if grep -qE "$PATTERN" "$probe/safe.py" 2>/dev/null; then
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
if grep -qE "$PATTERN" "$probe/nearmiss.py" 2>/dev/null; then
  echo "FAIL - self-probe: matched a number that merely contains a banned code"
  fail=1
else
  echo "ok - does not fire on numbers that merely contain a banned code"
fi

exit "$fail"
