#!/usr/bin/env bash
# Offline test for crt-monologue.sh's overscan-margin math -- extracts the
# exact left/right margin computation (kept in sync by hand) and checks it
# against a real temp display.conf, same pattern as test_monologue_width.sh.
set -uo pipefail
fail=0

check() {
  local desc="$1" expected="$2" got="$3"
  if [ "$got" = "$expected" ]; then
    echo "ok - $desc"
  else
    echo "FAIL - $desc: expected '$expected', got '$got'"
    fail=1
  fi
}

resolve_width() {
  # $1 = RAW_WIDTH, $2 = display.conf path (may not exist)
  bash -c '
    RAW_WIDTH="'"$1"'"
    DISPLAY_CONF="'"$2"'"
    margin_left=0
    margin_right=0
    if [ -f "$DISPLAY_CONF" ]; then
      margin_left=$(awk -F= "\$1==\"left\"{print \$2+0}" "$DISPLAY_CONF" 2>/dev/null)
      margin_right=$(awk -F= "\$1==\"right\"{print \$2+0}" "$DISPLAY_CONF" 2>/dev/null)
      [ -z "$margin_left" ] && margin_left=0
      [ -z "$margin_right" ] && margin_right=0
    fi
    WIDTH=$(( RAW_WIDTH - margin_left - margin_right ))
    [ "$WIDTH" -lt 1 ] && WIDTH=1
    echo "$WIDTH"
  '
}

TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

check "no conf file -> no-op" "40" "$(resolve_width 40 "$TMPDIR/nope.conf")"

conf="$TMPDIR/display.conf"
printf 'top=1\nbottom=1\nleft=3\nright=3\n' > "$conf"
check "conf margins shrink width" "34" "$(resolve_width 40 "$conf")"

conf2="$TMPDIR/display2.conf"
printf 'left=100\nright=100\n' > "$conf2"
check "never shrinks below 1" "1" "$(resolve_width 40 "$conf2")"

exit "$fail"
