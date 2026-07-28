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
# The over-match this file originally accepted came true (2026-07-28): the
# screensaver's live-tuned olive/brown palette uses real 256-color
# sequences (`\x1b[38;5;94m` -- palette index 94, a brown, nothing like
# bright blue), and `tests/test_screensaver.py` grew its own tokenizer
# plus a regression test naming those sequences. This check flagged that
# test file, i.e. the two enforcements of the same rule disagreed. The
# premise for the cheap trade ("nothing in this repo uses 256-color") is
# simply no longer true, so the check now excludes the 256-color
# selector form the way the Python tokenizer does: a banned code
# preceded by `;5;` is a palette index, not an SGR color code. Everything
# else still fires. Remaining accepted over-match: a TRUEcolor
# `\033[38;2;0;92;0m` (green component 92) would trip this -- nothing in
# the repo uses `38;2;`/`48;2;` and no lookbehind can tell a colour
# component from a code, so that one stays a loud false positive.
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
