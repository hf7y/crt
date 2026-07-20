#!/usr/bin/env bash
# Offline test for crt-monologue.sh's WIDTH resolution (env override > tput
# > hardcoded fallback) -- can't run the actual tail -f display loop
# without a real log/terminal, so this extracts and re-runs just the one
# line of logic under different conditions via a fake `tput` on PATH.
set -uo pipefail
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)"
FAKE_BIN="$(mktemp -d)"
trap 'rm -rf "$FAKE_BIN"' EXIT
fail=0

resolve_width() {
  # Mirrors the exact expression in crt-monologue.sh -- kept in sync by
  # hand; if that line changes, update this too.
  ( PATH="$FAKE_BIN:$PATH" bash -c '
      CRT_PAGER_WIDTH="'"${CRT_PAGER_WIDTH:-}"'"
      WIDTH="${CRT_PAGER_WIDTH:-$(tput cols 2>/dev/null || echo 40)}"
      echo "$WIDTH"
    ' )
}

check() {
  local desc="$1" expected="$2" got="$3"
  if [ "$got" = "$expected" ]; then
    echo "ok - $desc"
  else
    echo "FAIL - $desc: expected '$expected', got '$got'"
    fail=1
  fi
}

# Case 1: env override wins even when tput would report something else.
cat > "$FAKE_BIN/tput" <<'EOF'
#!/usr/bin/env bash
echo 100
EOF
chmod +x "$FAKE_BIN/tput"
CRT_PAGER_WIDTH=40 got=$(resolve_width)
check "env override wins over tput" "40" "$got"

# Case 2: no env override -> real tput value used.
unset CRT_PAGER_WIDTH
got=$(resolve_width)
check "tput value used when no override" "100" "$got"

# Case 3: tput fails (e.g. no tty) -> hardcoded 40 fallback.
cat > "$FAKE_BIN/tput" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
chmod +x "$FAKE_BIN/tput"
got=$(resolve_width)
check "hardcoded fallback when tput fails" "40" "$got"

exit "$fail"
