#!/usr/bin/env bash
# Offline test: a capture duck must be RELEASED even when its producer is
# killed mid-playback.
#
# Why this exists (2026-07-25): the CTL "mute" flag became a reference count
# (0343f21) so overlapping ducks compose. That fixed one race and created a
# worse failure mode -- under the old last-write-wins flag ANY later "mute 0"
# restored capture, so a duck whose producer died mid-sound got cleaned up by
# the next sound that played. With a counter, a leaked increment never comes
# back down and crt-stt-solo.py goes permanently deaf: no error, no crash,
# looks exactly like the mic died. Measured the same day: bash runs its EXIT
# trap on SIGTERM, but Python skips finally: blocks entirely -- so crt-tts.py
# (killed by `tmux kill-window`, a supervisor restart, pkill) was a real leak
# source and crt-earcon.sh was not.
#
# This asserts the observable contract for both producers: killed mid-aplay,
# the CTL file still ends with a balanced "mute 0". crt-stt-solo.py's
# MUTE_MAX_SECS watchdog is the backstop for what no handler can catch
# (SIGKILL, power loss) and is covered in tests/test_stt_solo_helpers.py.
set -uo pipefail
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)"
fail=0

FAKE_BIN="$(mktemp -d)"
WORK="$(mktemp -d)"
trap 'rm -rf "$FAKE_BIN" "$WORK"' EXIT

# aplay that blocks, so there is always a live playback to kill in the middle of.
cat > "$FAKE_BIN/aplay" <<'EOF'
#!/usr/bin/env bash
sleep 10
EOF
chmod +x "$FAKE_BIN/aplay"

# net "mute" balance of a CTL file: +1 per "mute 1", -1 per "mute 0".
# 0 = every duck released; >0 = a duck leaked and capture stays deaf.
mute_balance() {
  local f="$1" up down
  up=$(grep -cx "mute 1" "$f" 2>/dev/null || true)
  down=$(grep -cx "mute 0" "$f" 2>/dev/null || true)
  echo $(( ${up:-0} - ${down:-0} ))
}

# Both fatal signals are tested, not just SIGTERM. Re-measured 2026-07-25 with
# a real `tmux kill-window`: the pane process receives signal 1 (SIGHUP) -- the
# pty closes and the kernel hangs the process group up. So SIGHUP, not SIGTERM,
# is what the "killed by tmux kill-window" case in this project actually means,
# and Python skips finally: on it exactly as it does on SIGTERM. A handler that
# traps only SIGTERM passes the SIGTERM half of this test while still leaking
# the duck every time a console window is torn down mid-playback.
SIGNALS="TERM HUP"

cat > "$FAKE_BIN/espeak-ng" <<'EOF'
#!/usr/bin/env bash
while [ $# -gt 0 ]; do
  [ "$1" = "-w" ] && { : > "$2"; exit 0; }
  shift
done
exit 0
EOF
chmod +x "$FAKE_BIN/espeak-ng"

# --- crt-tts.py, killed mid-playback ----------------------------------------
# Driven through the real CLI entrypoint (not by importing play_wav), so this
# also covers __main__ actually installing the handler. A fake espeak-ng
# stands in for the synth backend -- the duck under test is playback's.
for sig in $SIGNALS; do
  CTL="$WORK/ctl-tts-$sig"
  CRT_CTL_FILE="$CTL" PATH="$FAKE_BIN:$PATH" \
    python3 "$BIN_DIR/crt-tts.py" --device handset "duck test" >/dev/null 2>&1 &
  tts_pid=$!
  for _ in $(seq 1 50); do            # wait for the duck to actually open
    [ -s "$CTL" ] && break
    sleep 0.1
  done
  if [ "$(mute_balance "$CTL")" -ne 1 ]; then
    echo "FAIL - crt-tts.py handset playback never opened a duck (CTL: $(cat "$CTL" 2>/dev/null))"
    fail=1
  fi
  kill -"$sig" "$tts_pid" 2>/dev/null
  wait "$tts_pid" 2>/dev/null

  if [ "$(mute_balance "$CTL")" -eq 0 ]; then
    echo "ok - crt-tts.py released its capture duck when SIG$sig'd mid-playback"
  else
    echo "FAIL - crt-tts.py leaked a capture duck on SIG$sig; capture would stay muted (CTL: $(tr '\n' '/' < "$CTL"))"
    fail=1
  fi
done

# --- crt-earcon.sh, killed mid-playback -------------------------------------
# sox is faked, not required. It used to be `if command -v sox`, with an
# `else echo skip` -- and this runner has no sox, so the crt-earcon.sh half of
# this file had never actually executed here despite the report that landed
# alongside it claiming both producers were covered (found 2026-07-25). The
# duck under test is the CTL file's, not the synth's.
cat > "$FAKE_BIN/sox" <<'EOF'
#!/usr/bin/env bash
for a in "$@"; do
  case "$a" in *.wav) : > "$a" ;; esac
done
exit 0
EOF
chmod +x "$FAKE_BIN/sox"

for sig in $SIGNALS; do
  CTL2="$WORK/ctl-earcon-$sig"
  CRT_CTL_FILE="$CTL2" PATH="$FAKE_BIN:$PATH" \
    bash "$BIN_DIR/crt-earcon.sh" ack --device handset >/dev/null 2>&1 &
  ear_pid=$!
  for _ in $(seq 1 50); do
    [ -s "$CTL2" ] && break
    sleep 0.1
  done
  if [ "$(mute_balance "$CTL2")" -ne 1 ]; then
    echo "FAIL - crt-earcon.sh handset playback never opened a duck (CTL: $(cat "$CTL2" 2>/dev/null))"
    fail=1
  fi
  kill -"$sig" "$ear_pid" 2>/dev/null
  wait "$ear_pid" 2>/dev/null

  if [ "$(mute_balance "$CTL2")" -eq 0 ]; then
    echo "ok - crt-earcon.sh released its capture duck when SIG$sig'd mid-playback"
  else
    echo "FAIL - crt-earcon.sh leaked a capture duck on SIG$sig (CTL: $(cat "$CTL2" 2>/dev/null | tr '\n' '/'))"
    fail=1
  fi
done

exit "$fail"
