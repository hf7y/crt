#!/usr/bin/env bash
# Offline test for bin/crt-pull.sh (crt#325 -- "potato pulls crt"): a
# fast-forward-only puller that restarts the tmux windows whose backing
# script changed. Exercises the git safety rules and the restart
# decision against a fake tmux, never a real console.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$DIR/../bin"
fail=0

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

REMOTE="$TMP/origin.git"
git init -q --bare "$REMOTE"

CLONE="$TMP/clone"
git clone -q "$REMOTE" "$CLONE" 2>/dev/null
(
  cd "$CLONE"
  git checkout -q -b main
  git config user.email test@example.com
  git config user.name test
  mkdir -p bin
  cp "$BIN_DIR/crt-pull.sh" bin/crt-pull.sh
  cp "$BIN_DIR/crt_console_windows.py" bin/crt_console_windows.py
  cat >bin/crt-console.sh <<'EOF'
#!/usr/bin/env bash
tmux new-window -d -t "$SESSION" -n stt -c "$BIN_DIR" "./crt-stt-supervisor.sh; exec bash"
tmux new-window -d -t "$SESSION" -n book -c "$BIN_DIR" "python3 ./crt-book-console.py; exec bash"
EOF
  echo seed >seed.txt
  git add -A
  git commit -q -m seed
  git push -q origin main
)

FAKEBIN="$TMP/fakebin"
mkdir -p "$FAKEBIN"
HOMEDIR="$TMP/home"
mkdir -p "$HOMEDIR"
TMUX_LOG="$TMP/tmux.log"
cat >"$FAKEBIN/tmux" <<EOF
#!/usr/bin/env bash
echo "\$@" >> "$TMUX_LOG"
case "\$1" in
  has-session) exit 0 ;;
  respawn-window) exit 0 ;;
esac
exit 0
EOF
chmod +x "$FAKEBIN/tmux"

run_pull() {
  (cd "$CLONE" && HOME="$HOMEDIR" PATH="$FAKEBIN:$PATH" CRT_TMUX_SESSION=claude bash bin/crt-pull.sh)
}

# --- already up to date: no-op, no tmux calls -------------------------------
: >"$TMUX_LOG"
run_pull >"$TMP/out.log" 2>&1
rc=$?
if [ "$rc" -eq 0 ] && [ ! -s "$TMUX_LOG" ]; then
  echo "PASS: up to date is a quiet no-op"
else
  echo "FAIL: up to date should exit 0 and touch no tmux window (rc=$rc)"
  fail=1
fi

# --- a new commit touching a mapped window's script restarts only that window
(
  cd "$TMP" && git clone -q -b main "$REMOTE" pusher >/dev/null 2>&1
  cd pusher
  git config user.email test@example.com
  git config user.name test
  echo "changed" >>bin/crt-stt-supervisor.sh
  git add -A
  git commit -q -m "touch stt supervisor"
  git push -q origin main
)
: >"$TMUX_LOG"
run_pull >"$TMP/out.log" 2>&1
rc=$?
if [ "$rc" -eq 0 ] && grep -q "respawn-window -k -t claude:stt" "$TMUX_LOG" && ! grep -q "claude:book" "$TMUX_LOG"; then
  echo "PASS: only the window whose script changed gets respawned"
else
  echo "FAIL: expected exactly the 'stt' window respawned"
  cat "$TMUX_LOG"
  fail=1
fi

# --- a dirty tree refuses to pull, even with a real update waiting ----------
(
  cd "$TMP/pusher"
  echo "again" >>bin/crt-stt-supervisor.sh
  git add -A
  git commit -q -m "another touch"
  git push -q origin main
)
before_head="$(cd "$CLONE" && git rev-parse HEAD)"
(cd "$CLONE" && echo dirty >>seed.txt)
: >"$TMUX_LOG"
run_pull >"$TMP/out.log" 2>&1
rc=$?
after_head="$(cd "$CLONE" && git rev-parse HEAD)"
if [ "$rc" -ne 0 ] && [ "$after_head" = "$before_head" ] && [ ! -s "$TMUX_LOG" ]; then
  echo "PASS: a dirty tree is refused, HEAD untouched"
else
  echo "FAIL: a dirty tree should refuse the pull and touch nothing (rc=$rc)"
  fail=1
fi
(cd "$CLONE" && git checkout -q -- seed.txt)

# --- a local commit not on origin is not a fast-forward: refused -----------
(
  cd "$CLONE"
  echo "local-only" >>seed.txt
  git add -A
  git commit -q -m "local divergence, never pushed"
)
before_head="$(cd "$CLONE" && git rev-parse HEAD)"
: >"$TMUX_LOG"
run_pull >"$TMP/out.log" 2>&1
rc=$?
after_head="$(cd "$CLONE" && git rev-parse HEAD)"
if [ "$rc" -ne 0 ] && [ "$after_head" = "$before_head" ]; then
  echo "PASS: a non-fast-forward history is refused"
else
  echo "FAIL: a diverged local commit should refuse the merge (rc=$rc)"
  fail=1
fi
(cd "$CLONE" && git reset -q --hard origin/main 2>/dev/null || true)

# --- no live tmux session: pull still happens, restart is skipped, not fatal
cat >"$FAKEBIN/tmux" <<'EOF'
#!/usr/bin/env bash
[ "$1" = has-session ] && exit 1
exit 0
EOF
chmod +x "$FAKEBIN/tmux"
(
  cd "$TMP/pusher"
  git pull -q origin main
  echo "no session update" >>bin/crt-stt-supervisor.sh
  git add -A
  git commit -q -m "update with no console running"
  git push -q origin main
)
run_pull >"$TMP/out.log" 2>&1
rc=$?
after_head="$(cd "$CLONE" && git rev-parse HEAD)"
target_head="$(cd "$TMP/pusher" && git rev-parse HEAD)"
if [ "$rc" -eq 0 ] && [ "$after_head" = "$target_head" ]; then
  echo "PASS: pull still lands with no tmux session running"
else
  echo "FAIL: expected the pull to succeed even with no console running (rc=$rc)"
  fail=1
fi

if [ "$fail" -eq 0 ]; then
  echo "ALL PASS"
fi
exit $fail
