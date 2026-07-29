#!/usr/bin/env bash
# Offline test for bin/crt-conf.sh and its two consumers.
#
# The bug, live 2026-07-29: the console's identity (CRT_WAKE_WORD,
# CRT_EARCON_DEVICE, ...) lived only as exports in ~/.bash_profile.
# Restarting the `stt` tmux window over ssh -- a non-login shell -- gave
# crt-stt-solo.py NONE of them, so it fell back to its library defaults:
# earcons into the handset instead of the room, wake word "claude"
# instead of "potato". Everything downstream reported healthy. The mic
# worked, the meter moved, the log filled. It was just deaf to its own
# name and beeping somewhere nobody was listening.
#
# So the contract under test is specifically: capture restarted WITHOUT a
# login shell, and with an environment stripped of every CRT_* var, still
# comes up with the configured identity.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$DIR/../bin"
fail=0

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# --- 1. Executing the loader instead of sourcing it must fail loudly ----
# It would otherwise be a perfect silent no-op: every assignment lands in
# a shell that immediately exits, exit 0, nothing configured.
out="$(bash "$BIN/crt-conf.sh" 2>&1)"; rc=$?
if [ "$rc" -eq 2 ] && printf '%s' "$out" | grep -qi "must be SOURCED"; then
  echo "PASS: crt-conf.sh refuses to be executed (exit 2, says why)"
else
  echo "FAIL: executing crt-conf.sh gave rc=$rc out='$out' -- expected a loud refusal"
  fail=1
fi

# --- 2. A hand-restarted supervisor picks the config up by itself ------
# Faked all the way down: a temp BIN_DIR holding real copies of the two
# scripts under test, a `python3` shim standing in for crt-stt-solo.py
# that just dumps its own environment, and a temp HOME holding the conf.
FAKEBIN="$TMP/fakebin"; mkdir -p "$FAKEBIN"
ENVDUMP="$TMP/child.env"
cat > "$FAKEBIN/python3" <<'EOF'
#!/usr/bin/env bash
env > "$CHILD_ENV_DUMP"
exit 0
EOF
chmod +x "$FAKEBIN/python3"
# The supervisor fires an earcon on every child exit. Real sox/aplay on a
# test machine would be an actual noise from a test run; stub it.
cat > "$FAKEBIN/crt-earcon-stub" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF

TESTBIN="$TMP/bin"; mkdir -p "$TESTBIN"
cp "$BIN/crt-conf.sh" "$BIN/crt-stt-supervisor.sh" "$TESTBIN/"
cp "$FAKEBIN/crt-earcon-stub" "$TESTBIN/crt-earcon.sh"

FAKEHOME="$TMP/home"; mkdir -p "$FAKEHOME/.crt"
cat > "$FAKEHOME/.crt/console.conf" <<'EOF'
export CRT_WAKE_WORD="${CRT_WAKE_WORD:-potato}"
export CRT_EARCON_DEVICE="${CRT_EARCON_DEVICE:-tv}"
export CRT_WHISPER_SERVER="${CRT_WHISPER_SERVER:-http://whisper.example:8991/transcribe}"
EOF

run_supervisor() {
  # env -i: not merely "unset the CRT_* vars we know about" but a genuinely
  # empty environment, which is the honest model of a fresh non-login shell.
  : > "$ENVDUMP"
  env -i PATH="$FAKEBIN:/usr/bin:/bin" HOME="$FAKEHOME" \
    CHILD_ENV_DUMP="$ENVDUMP" \
    CRT_STT_SUP_MIN_HEALTHY_SECS=1 \
    "$@" \
    timeout 10 bash "$TESTBIN/crt-stt-supervisor.sh" >/dev/null 2>&1
}

run_supervisor
for pair in CRT_WAKE_WORD=potato CRT_EARCON_DEVICE=tv; do
  if grep -qx "$pair" "$ENVDUMP"; then
    echo "PASS: restarted capture inherits $pair from ~/.crt/console.conf"
  else
    echo "FAIL: $pair missing from the child env -- got: $(grep '^CRT_' "$ENVDUMP" | tr '\n' ' ')"
    fail=1
  fi
done

# --- 3. An explicit env var still beats the file ------------------------
# The ${VAR:-default} form in the conf is what makes a one-off override
# (a test, a bisect, crt-console.sh passing something down) possible at
# all. A bare assignment in the conf would silently win instead.
run_supervisor CRT_EARCON_DEVICE=handset
if grep -qx "CRT_EARCON_DEVICE=handset" "$ENVDUMP"; then
  echo "PASS: an explicit CRT_EARCON_DEVICE override beats console.conf"
else
  echo "FAIL: console.conf clobbered an explicit CRT_EARCON_DEVICE override"
  fail=1
fi

# --- 4. brain.conf still wins on brain routing -------------------------
# It is read last on purpose: it is the file Zach flips at runtime.
cat > "$FAKEHOME/.crt/brain.conf" <<'EOF'
CRT_CLAUDE_SSH_HOST=dexter
export CRT_CLAUDE_SSH_HOST
EOF
cat >> "$FAKEHOME/.crt/console.conf" <<'EOF'
export CRT_CLAUDE_SSH_HOST="${CRT_CLAUDE_SSH_HOST:-wrong-host}"
EOF
run_supervisor
if grep -qx "CRT_CLAUDE_SSH_HOST=dexter" "$ENVDUMP"; then
  echo "PASS: brain.conf outranks console.conf on brain routing"
else
  echo "FAIL: console.conf outranked brain.conf -- got: $(grep CLAUDE_SSH "$ENVDUMP")"
  fail=1
fi

# --- 5. crt-console.sh must not retype console-wide config -------------
# This is the regression guard on the actual mechanism of the bug: the
# values were spelled out in ONE launch string, so the launch string was
# the only way to get them right, so restarting the window any other way
# was quietly a different configuration.
sttline="$(grep -n 'crt-stt-supervisor.sh' "$BIN/crt-console.sh" | grep 'new-window\|CRT_STT_SINK')"
retyped=0
for var in CRT_WHISPER_SERVER CRT_AUDIO_DEV CRT_EARCON_DEVICE CRT_WAKE_WORD CRT_CLAUDE_SSH_HOST; do
  if printf '%s' "$sttline" | grep -q "$var="; then
    echo "FAIL: crt-console.sh still retypes $var into the stt window command"
    retyped=1; fail=1
  fi
done
[ "$retyped" -eq 0 ] && echo "PASS: crt-console.sh's stt window carries only window-specific env"

# --- 6. The shipped example is a real, sourceable file -----------------
# A broken example is worse than none: it is what the next person copies.
if ( set -e; unset CRT_WAKE_WORD; . "$DIR/../console.conf.example" >/dev/null 2>&1; [ -n "${CRT_WAKE_WORD:-}" ] ); then
  echo "PASS: console.conf.example sources cleanly and defines a wake word"
else
  echo "FAIL: console.conf.example does not source cleanly"
  fail=1
fi

exit "$fail"
