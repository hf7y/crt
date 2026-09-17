#!/usr/bin/env bash
set -uo pipefail
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

BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)"
SCRATCH_REPO="$(mktemp -d)"
SCRATCH_HOME="$(mktemp -d)"
FAKE_BIN="$(mktemp -d)"
trap 'rm -rf "$SCRATCH_REPO" "$SCRATCH_HOME" "$FAKE_BIN"' EXIT

mkdir -p "$SCRATCH_REPO/bin"
cp "$BIN_DIR/crt-self-repair.sh" "$SCRATCH_REPO/bin/crt-self-repair.sh"

(
  cd "$SCRATCH_REPO"
  git init -q
  git config user.email test@example.com
  git config user.name test
  echo "line-a" > tracked.txt
  git add tracked.txt
  git commit -q -m initial
  echo "line-b" > tracked.txt
)

cat > "$FAKE_BIN/claude" <<'EOF'
#!/usr/bin/env bash
echo "line-c" >> tracked.txt
kill -9 $$
EOF
chmod +x "$FAKE_BIN/claude"

HOME="$SCRATCH_HOME" PATH="$FAKE_BIN:$PATH" bash "$SCRATCH_REPO/bin/crt-self-repair.sh"
run_rc=$?

check "self-repair.sh itself exits clean even though claude was killed mid-run" "0" "$run_rc"

log_count="$(git -C "$SCRATCH_REPO" log --oneline | wc -l | tr -d ' ')"
check "both the pre-run and post-run commits landed on top of the initial one" "3" "$log_count"

check "pre-run commit captured the dirty state from before claude ran" \
  "1" "$(git -C "$SCRATCH_REPO" log --format=%s | grep -c 'self-repair: pre-run snapshot')"

check "post-run commit captured claude's partial edit despite the crash" \
  "1" "$(git -C "$SCRATCH_REPO" log --format=%s | grep -c 'self-repair: post-run snapshot')"

check "the crashed edit actually made it into the committed file, not just the working tree" \
  "line-c" "$(git -C "$SCRATCH_REPO" show HEAD:tracked.txt | tail -1)"

if [ "$fail" -eq 0 ]; then
  echo "ALL GREEN - test_self_repair.sh"
else
  echo "SOMETHING FAILED - test_self_repair.sh"
fi
exit "$fail"
