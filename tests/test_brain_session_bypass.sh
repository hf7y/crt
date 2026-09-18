#!/usr/bin/env bash
# Offline test for bin/crt-brain-session.sh's 2026-07-29 bypass-permissions
# changes -- see that script's own CRT_BRAIN_CLAUDE_ARGS comment for why a
# brain with no keyboard cannot afford a permission prompt. Two things
# under test: the brain must START bypassed, and `status` must be able to
# say a session is up but not answering. No real tmux/claude -- a shim
# records what it was asked to do and replays a canned pane.
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

# --- 7. An installed copy matching the repo reports no drift -----------
INSTALLED_MATCH="$TMP/installed_match"
cp "$DIR/../bin/crt-brain-shell.py" "$INSTALLED_MATCH"
printf '❯ ready\n' > "$PANE"
out="$(run TMUX_HAS_SESSION=0 CRT_BRAIN_INSTALLED="$INSTALLED_MATCH" status 2>&1)"; rc=$?
if [ "$rc" -eq 0 ] && ! printf '%s' "$out" | grep -q "DRIFT"; then
  echo "PASS: status reports no drift when the installed copy matches the repo"
else
  echo "FAIL: matching installed copy reported drift -- rc=$rc out='$out'"
  fail=1
fi

# --- 8. An installed copy diverging from the repo is DRIFT, not silence
INSTALLED_DIFF="$TMP/installed_diff"
printf '#!/usr/bin/env python3\n# not the repo copy\n' > "$INSTALLED_DIFF"
printf '❯ ready\n' > "$PANE"
out="$(run TMUX_HAS_SESSION=0 CRT_BRAIN_INSTALLED="$INSTALLED_DIFF" status 2>&1)"; rc=$?
if [ "$rc" -ne 0 ] && printf '%s' "$out" | grep -q "DRIFT"; then
  echo "PASS: status reports DRIFT (and a nonzero exit) when installed differs from the repo"
else
  echo "FAIL: diverged installed copy not reported -- rc=$rc out='$out'"
  fail=1
fi

# --- 9. A missing installed copy is a different failure than DRIFT -----
printf '❯ ready\n' > "$PANE"
out="$(run TMUX_HAS_SESSION=0 CRT_BRAIN_INSTALLED="$TMP/does-not-exist" status 2>&1)"; rc=$?
if [ "$rc" -ne 0 ] && printf '%s' "$out" | grep -q "MISSING"; then
  echo "PASS: status reports MISSING when the installed copy does not exist"
else
  echo "FAIL: missing installed copy not reported -- rc=$rc out='$out'"
  fail=1
fi

# --- 10. The bypass-confirmation screen is a parked state too ----------
cat > "$PANE" <<'EOF'
 Bypass Permissions mode
 This will bypass all permission checks. Only use in a sandboxed environment.
 ❯ 2. Yes, I accept the risk
EOF
out="$(run TMUX_HAS_SESSION=0 status 2>&1)"; rc=$?
if [ "$rc" -ne 0 ] && printf '%s' "$out" | grep -q "bypass-permissions confirmation"; then
  echo "PASS: the bypass-permissions confirmation screen is caught as parked"
else
  echo "FAIL: bypass-confirmation park not detected -- rc=$rc out='$out'"
  fail=1
fi

# --- 13. Signed out: healthy-looking pane, cannot answer a thing -----------
# The one that got through. Not a modal -- an ordinary ready prompt with an
# error in the scrollback -- so cases 3, 4 and 10 all pass it. Live on
# 2026-09-18: status said UP for an hour, SEND returned OK because tmux
# send-keys really did succeed, and every utterance was answered with
# "Login expired".
cat > "$PANE" <<'EOF'
❯ Reply with exactly: BRAIN OK
● Login expired · Please run /login
✻ Worked for 0s
❯
  ⏵⏵ bypass permissions on (shift+tab to cycle)
EOF
out="$(run TMUX_HAS_SESSION=0 status 2>&1)"; rc=$?
if [ "$rc" -ne 0 ] && printf '%s' "$out" | grep -q "signed out"; then
  echo "PASS: an expired login is reported, not called UP"
else
  echo "FAIL: signed-out brain reported healthy -- rc=$rc out='$out'"
  fail=1
fi

# --- 11-12. claude off PATH, as a non-interactive ssh actually sees it ---
# `ssh dexter '.../crt-brain-session.sh ensure'` gets a PATH without
# ~/.local/bin, so the 2026-09-18 restart failed with "claude not on PATH"
# on a box where an interactive shell found it. PATH here is the shim dir
# ALONE -- inheriting the real one would let a developer's own claude
# satisfy command -v and pass the test for the wrong reason.
BARE="$TMP/bare"; mkdir -p "$BARE"
cp "$FAKEBIN/tmux" "$BARE/tmux"
# Mirror /usr/bin and /bin into $BARE via symlinks, EXCLUDING any `claude`
# found there, rather than trusting the two dirs are claude-free outright.
# A seat with Claude Code installed system-wide (e.g. /usr/bin/claude, a
# symlink into the npm global tree -- true on this box) would otherwise
# make `command -v claude` succeed against those dirs and pass this test
# for the wrong reason -- the same failure mode this comment already knew
# to avoid for a per-user ~/.local/bin/claude.
for d in /usr/bin /bin; do
  [ -d "$d" ] || continue
  for f in "$d"/*; do
    name="$(basename "$f")"
    [ "$name" = "claude" ] && continue
    [ -e "$BARE/$name" ] && continue
    ln -s "$f" "$BARE/$name" 2>/dev/null
  done
done
BARE_PATH="$BARE"
mkdir -p "$TMP/home/.local/bin"
printf '#!/usr/bin/env bash\nexit 0\n' > "$TMP/home/.local/bin/claude"
chmod +x "$TMP/home/.local/bin/claude"

BASH_BIN="$(command -v bash)"
run_bare() {
  local envs=()
  while [ "$#" -gt 0 ] && [ "${1#*=}" != "$1" ]; do envs+=("$1"); shift; done
  env PATH="$BARE_PATH" HOME="$TMP/home" "${envs[@]}" "$BASH_BIN" "$SCRIPT" "$@"
}

# --- 11. ...falls back to ~/.local/bin/claude rather than refusing ------
: > "$LOG"
printf '❯ ready\n' > "$PANE"
# Asserted on the new-session line, not the exit code: the tmux shim reports
# has-session false on every call, so the post-start liveness check always
# says the session died. What is under test is WHICH binary got launched.
out="$(run_bare TMUX_HAS_SESSION=1 ensure 2>&1)"; rc=$?
if grep -q "$TMP/home/.local/bin/claude" "$LOG"; then
  echo "PASS: claude off PATH falls back to ~/.local/bin/claude"
else
  echo "FAIL: no fallback when claude is off PATH -- rc=$rc out='$out' log='$(cat "$LOG")'"
  fail=1
fi

# --- 12. ...but an explicitly named binary that is missing still fails --
# Starting a DIFFERENT claude than the one asked for is worse than not
# starting, so the fallback is scoped to the unset case only.
: > "$LOG"
out="$(run_bare TMUX_HAS_SESSION=1 CRT_BRAIN_CLAUDE="$TMP/no-such-claude" ensure 2>&1)"; rc=$?
if [ "$rc" -ne 0 ] && printf '%s' "$out" | grep -q "not on PATH"; then
  echo "PASS: an explicit CRT_BRAIN_CLAUDE that is missing stays a hard error"
else
  echo "FAIL: explicit missing CRT_BRAIN_CLAUDE was silently replaced -- rc=$rc out='$out' log='$(cat "$LOG")'"
  fail=1
fi

exit "$fail"
