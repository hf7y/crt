#!/usr/bin/env bash
# Offline test for bin/crt-brain-session.sh's 2026-07-29 changes.
#
# The bug: the dexter brain was started with a bare `claude`. Its only
# input is `tmux send-keys` from potato, driven by someone speaking into
#   [rest: vault:crt/header-archaeology-20260817.md]
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$DIR/../bin/crt-brain-session.sh"
fail=0

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
FAKEBIN="$TMP/bin"; mkdir -p "$FAKEBIN"

# `claude` only has to exist on PATH -- the script command -v's it.
printf '#!/usr/bin/env bash\nexit 0\n' > "$FAKEBIN/claude"
chmod +x "$FAKEBIN/claude"

# tmux shim. TMUX_HAS_SESSION decides whether a session "exists";
# TMUX_PANE_FILE is what capture-pane replays; new-session args are
# appended to TMUX_LOG.
cat > "$FAKEBIN/tmux" <<'EOF'
#!/usr/bin/env bash
case "$1" in
  has-session)  exit "${TMUX_HAS_SESSION:-1}" ;;
  new-session)  printf '%s\n' "$*" >> "$TMUX_LOG"; exit 0 ;;
  capture-pane) cat "$TMUX_PANE_FILE" 2>/dev/null; exit 0 ;;
  kill-session) exit 0 ;;
  *) exit 0 ;;
esac
EOF
chmod +x "$FAKEBIN/tmux"

PANE="$TMP/pane.txt"
LOG="$TMP/tmux.log"
export TMUX_PANE_FILE="$PANE" TMUX_LOG="$LOG"

# run VAR=val... <subcommand> -- splits leading env assignments off the
# argument list, which a bare `CMD "$@"` cannot do.
run() {
  local envs=()
  while [ "$#" -gt 0 ] && [ "${1#*=}" != "$1" ]; do envs+=("$1"); shift; done
  env PATH="$FAKEBIN:$PATH" HOME="$TMP/home" "${envs[@]}" bash "$SCRIPT" "$@"
}

# --- 1. The brain starts with permissions bypassed by default ----------
: > "$LOG"
printf '❯ ready\n' > "$PANE"
run TMUX_HAS_SESSION=1 ensure >/dev/null 2>&1
if grep -q -- "--permission-mode bypassPermissions" "$LOG"; then
  echo "PASS: ensure starts claude with --permission-mode bypassPermissions"
else
  echo "FAIL: brain started without bypass -- new-session was: $(cat "$LOG")"
  fail=1
fi

# --- 2. ...and that is overridable, not welded in ----------------------
: > "$LOG"
run TMUX_HAS_SESSION=1 CRT_BRAIN_CLAUDE_ARGS="--model sonnet" ensure >/dev/null 2>&1
if grep -q -- "--model sonnet" "$LOG" && ! grep -q -- "bypassPermissions" "$LOG"; then
  echo "PASS: CRT_BRAIN_CLAUDE_ARGS overrides the default"
else
  echo "FAIL: CRT_BRAIN_CLAUDE_ARGS was not honored -- got: $(cat "$LOG")"
  fail=1
fi

# --- 3. A session parked on a permission prompt is NOT healthy ---------
# This is the whole point. Session exists, pane paints, and `status` used
# to print UP and exit 0 for exactly this pane.
cat > "$PANE" <<'EOF'
 Bash command
   ls ~/.local/bin/
 Do you want to proceed?
 ❯ 1. Yes
   2. No
EOF
out="$(run TMUX_HAS_SESSION=0 status 2>&1)"; rc=$?
if [ "$rc" -ne 0 ] && printf '%s' "$out" | grep -q "NOT ANSWERING"; then
  echo "PASS: status reports a permission-prompt-parked brain as not answering (rc=$rc)"
else
  echo "FAIL: parked brain reported as healthy -- rc=$rc out='$out'"
  fail=1
fi

# --- 4. The trust-folder prompt is still caught (2026-07-28 case) ------
cat > "$PANE" <<'EOF'
 Do you trust the files in this folder?
 ❯ 1. Yes, I trust the files
EOF
out="$(run TMUX_HAS_SESSION=0 status 2>&1)"; rc=$?
if [ "$rc" -ne 0 ] && printf '%s' "$out" | grep -q "trust-folder"; then
  echo "PASS: the older trust-folder park is still detected"
else
  echo "FAIL: trust-folder park regressed -- rc=$rc out='$out'"
  fail=1
fi

# --- 5. A genuinely ready brain still reports UP ------------------------
# A check that only ever says "broken" is not a check.
printf '❯ \n  ready for input\n' > "$PANE"
out="$(run TMUX_HAS_SESSION=0 CRT_BRAIN_INSTALLED="$FAKEBIN/claude" status 2>&1)"; rc=$?
if printf '%s' "$out" | grep -q "is UP" && ! printf '%s' "$out" | grep -q "NOT ANSWERING"; then
  echo "PASS: a ready pane still reports UP"
else
  echo "FAIL: a healthy brain was misreported -- rc=$rc out='$out'"
  fail=1
fi

# --- 6. The brain prefers its own worktree over the shared checkout ----
# Two writers in one checkout is how a spoken commit and a hand edit
# collide. If ~/crt-brain exists, that is where the brain runs.
mkdir -p "$TMP/home/crt-brain"
: > "$LOG"
printf '❯ ready\n' > "$PANE"
out="$(run TMUX_HAS_SESSION=1 ensure 2>&1)"
if printf '%s' "$out" | grep -q "crt-brain"; then
  echo "PASS: ensure runs the brain in the dedicated voice worktree when present"
else
  echo "FAIL: voice worktree ignored -- out='$out'"
  fail=1
fi

exit "$fail"
