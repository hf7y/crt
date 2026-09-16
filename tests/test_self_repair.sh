#!/usr/bin/env bash
# Offline test for bin/crt-self-repair.sh's load-bearing claim: the pre/post
# -run `git commit` calls happen regardless of what `claude -p` does, so a
# revert point exists even if it crashes mid-edit. No real `claude` or
# network involved -- a stub in a throwaway repo stands in for it.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fail=0

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

REPO="$TMP/repo"
mkdir -p "$REPO/bin"
cp "$DIR/../bin/crt-self-repair.sh" "$REPO/bin/crt-self-repair.sh"
(
  cd "$REPO"
  git init -q
  git config user.email "test@example.com"
  git config user.name "test"
  echo "seed" > seed.txt
  git add -A
  git commit -q -m "seed"
)

FAKEBIN="$TMP/fakebin"
mkdir -p "$FAKEBIN"
HOMEDIR="$TMP/home"
mkdir -p "$HOMEDIR"

# $1 = fake claude's exit code, $2 = 1 if it should edit a tracked file first
run_self_repair() {
  cat > "$FAKEBIN/claude" <<EOF
#!/usr/bin/env bash
if [ "$2" = "1" ]; then
  echo "edited" >> "$REPO/edited-by-claude.txt"
fi
exit $1
EOF
  chmod +x "$FAKEBIN/claude"
  ( cd "$REPO" && HOME="$HOMEDIR" PATH="$FAKEBIN:$PATH" bash bin/crt-self-repair.sh )
}

# --- claude "crashes" (nonzero exit) after editing a file: the post-run
# commit must still run and must capture that edit. If the script had
# stopped at the crash instead of continuing past it, the edit would sit
# untracked forever with no revert point.
before_head="$(cd "$REPO" && git rev-parse HEAD)"
run_self_repair 1 1 >/dev/null 2>&1
after_head="$(cd "$REPO" && git rev-parse HEAD)"
if [ "$after_head" != "$before_head" ] \
  && (cd "$REPO" && git log -1 --format=%s) | grep -q "post-run snapshot"; then
  echo "PASS: a crashing claude still gets a post-run commit"
else
  echo "FAIL: no post-run commit landed after claude exited nonzero"
  fail=1
fi
if (cd "$REPO" && git show --stat HEAD | grep -q "edited-by-claude.txt"); then
  echo "PASS: the edit claude made before crashing is in that commit"
else
  echo "FAIL: post-run commit did not capture the crash-time edit"
  fail=1
fi

# --- a dirty tree left over from a previous incomplete run gets its own
# pre-run snapshot before claude is even invoked, and a claude run that
# changes nothing afterward is logged, not silently dropped.
( cd "$REPO" && echo "stray" > stray.txt )
STAMP_LOG_DIR="$HOMEDIR/reports/crt-self-repair"
rm -rf "$STAMP_LOG_DIR"
before_head="$(cd "$REPO" && git rev-parse HEAD)"
rc=0
run_self_repair 0 0 >/dev/null 2>&1 || rc=$?
if [ "$rc" -eq 0 ]; then
  echo "PASS: a claude run with nothing to do still exits 0"
else
  echo "FAIL: exited $rc"
  fail=1
fi
pre_commit="$(cd "$REPO" && git log --format=%s "$before_head"..HEAD | tail -1)"
if printf '%s' "$pre_commit" | grep -q "pre-run snapshot" \
  && (cd "$REPO" && git show --stat "$before_head..HEAD" | grep -q "stray.txt"); then
  echo "PASS: the stray uncommitted file got its own pre-run snapshot"
else
  echo "FAIL: pre-existing dirty state was not snapshotted before claude ran"
  fail=1
fi
if grep -rl "nothing changed" "$STAMP_LOG_DIR" >/dev/null 2>&1; then
  echo "PASS: a no-op post-run is logged as such, not silent"
else
  echo "FAIL: no-op post-run left no 'nothing changed' record"
  fail=1
fi

if [ "$fail" -eq 0 ]; then
  echo "ALL GREEN"
else
  echo "SOMETHING FAILED"
fi
exit "$fail"
