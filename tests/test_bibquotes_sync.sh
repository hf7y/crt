#!/usr/bin/env bash
set -uo pipefail
fail=0
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$DIR/../bin/crt-bibquotes-sync.sh"

check() {
  local desc="$1" expected="$2" got="$3"
  if [ "$got" = "$expected" ]; then
    echo "ok - $desc"
  else
    echo "FAIL - $desc: expected '$expected', got '$got'"
    fail=1
  fi
}

TMPDIR_ROOT="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_ROOT"' EXIT

STUB_DIR="$TMPDIR_ROOT/stub"
mkdir -p "$STUB_DIR"
cat > "$STUB_DIR/smbclient" <<'STUB'
#!/usr/bin/env bash
tmp_path="${4##* }"
echo "$tmp_path" > "$FAKE_SMBCLIENT_TMP_RECORD"
if [ "${FAKE_SMBCLIENT_EXIT:-0}" = "0" ]; then
  printf '%s' "$FAKE_SMBCLIENT_CONTENT" > "$tmp_path"
fi
exit "${FAKE_SMBCLIENT_EXIT:-0}"
STUB
chmod +x "$STUB_DIR/smbclient"

run_sync() {
  PATH="$STUB_DIR:$PATH" \
  CRT_BIBQUOTES_SHARE="//fake/share" \
  CRT_BIBQUOTES_REMOTE_FILE="quotes.txt" \
  CRT_BIBQUOTES_PATH="$LOCAL_PATH" \
  FAKE_SMBCLIENT_EXIT="$FAKE_SMBCLIENT_EXIT" \
  FAKE_SMBCLIENT_CONTENT="${FAKE_SMBCLIENT_CONTENT:-}" \
  FAKE_SMBCLIENT_TMP_RECORD="$TMPDIR_ROOT/tmp_record" \
  bash "$SCRIPT"
}

CACHE_DIR="$TMPDIR_ROOT/case-a"
LOCAL_PATH="$CACHE_DIR/quotes.txt"
FAKE_SMBCLIENT_EXIT=0
FAKE_SMBCLIENT_CONTENT="fresh quote"
run_sync >/dev/null 2>&1
check "a successful fetch becomes the current cache" "fresh quote" "$(cat "$LOCAL_PATH" 2>/dev/null)"

CACHE_DIR="$TMPDIR_ROOT/case-b"
LOCAL_PATH="$CACHE_DIR/quotes.txt"
FAKE_SMBCLIENT_EXIT=1
FAKE_SMBCLIENT_CONTENT=""
run_sync >/dev/null 2>&1
check "a failed fetch with no prior cache creates no truncated/partial file" "absent" \
  "$([ -e "$LOCAL_PATH" ] && echo present || echo absent)"
tmp_from_failure="$(cat "$TMPDIR_ROOT/tmp_record")"
check "the failed fetch's temp file is removed, not left behind" "absent" \
  "$([ -e "$tmp_from_failure" ] && echo present || echo absent)"

CACHE_DIR="$TMPDIR_ROOT/case-c"
LOCAL_PATH="$CACHE_DIR/quotes.txt"
mkdir -p "$CACHE_DIR"
printf '%s' "last good quote" > "$LOCAL_PATH"
FAKE_SMBCLIENT_EXIT=1
run_sync >/dev/null 2>&1
check "a failed fetch does not disturb the last good cache -- idle-bait keeps serving it" \
  "last good quote" "$(cat "$LOCAL_PATH")"

exit "$fail"
