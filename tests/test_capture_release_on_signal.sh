#!/usr/bin/env bash
# Offline test: when crt-stt-solo.py is stopped, it must RELEASE the mic --
# i.e. its arecord child must actually be gone, not merely signalled.
#
# READ THIS BEFORE TRUSTING IT -- the four assertions per signal are not all
#   [rest: vault:crt/header-archaeology-20260817.md]
set -uo pipefail
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)"
fail=0

FAKE_BIN="$(mktemp -d)"
WORK="$(mktemp -d)"
trap 'rm -rf "$FAKE_BIN" "$WORK"' EXIT

# An arecord that behaves like a healthy capture: announces a capture card for
# name resolution, records its own pid, then streams silence forever.
cat > "$FAKE_BIN/arecord" <<'EOF'
#!/usr/bin/env bash
if [ "${1:-}" = "-l" ]; then
  echo "**** List of CAPTURE Hardware Devices ****"
  echo "card 1: Fake [Fake USB Audio], device 0: USB Audio [USB Audio]"
  exit 0
fi
echo "$$" > "$FAKE_PIDFILE"
exec dd if=/dev/zero bs=3200 2>/dev/null
EOF
chmod +x "$FAKE_BIN/arecord"

for sig in TERM HUP; do
  PIDF="$WORK/arecord.pid.$sig"
  rm -f "$PIDF"

  # Launched WITHOUT setsid deliberately, so $! is python's own pid. `kill`
  # targets a single process anyway, so nothing here needs its own process
  # group -- while `setsid` forks when its caller is a process-group leader,
  # which makes $! the already-exited setsid parent. Signalling that is a
  # no-op, and every assertion below would then pass vacuously. (Resolving the
  # pid with `pgrep -f ... | head -1` instead has the same trap from the other
  # end: setsid's own argv contains the script path too.)
  FAKE_PIDFILE="$PIDF" CRT_STT_SINK=stdout CRT_AUDIO_DEV=plughw:9,9 \
    PATH="$FAKE_BIN:$PATH" \
    python3 -u "$BIN_DIR/crt-stt-solo.py" >"$WORK/out.$sig" 2>&1 &
  py_pid=$!

  for _ in $(seq 1 60); do          # wait until capture is genuinely running
    [ -s "$PIDF" ] && break
    sleep 0.1
  done
  arecord_pid="$(cat "$PIDF" 2>/dev/null || true)"

  if [ -z "$arecord_pid" ]; then
    echo "FAIL - SIG$sig: fake arecord never started; test proves nothing"
    fail=1
    kill -9 "$py_pid" 2>/dev/null
    continue
  fi

  kill -"$sig" "$py_pid" 2>/dev/null
  wait "$py_pid" 2>/dev/null
  py_rc=$?
  # Give the handler room to terminate + wait for the child.
  # `kill -0` is the wrong instrument here: it succeeds on a zombie, which
  # holds no device and is exactly what a correctly-reaped-but-not-yet-
  # collected child looks like. Ask for the process STATE and treat Z as gone.
  released=0
  for _ in $(seq 1 60); do
    st="$(ps -o stat= -p "$arecord_pid" 2>/dev/null | tr -d ' ')"
    case "$st" in
      ""|Z*) released=1; break ;;
    esac
    sleep 0.1
  done

  if [ "$released" -eq 1 ]; then
    echo "ok - crt-stt-solo.py released the capture device when SIG$sig'd"
  else
    echo "FAIL - SIG$sig orphaned arecord (pid $arecord_pid); it still holds the mic and the next run cannot open it"
    fail=1
    kill -9 "$arecord_pid" 2>/dev/null
  fi

  # A deliberate stop is not a capture failure: it must not print the
  # CAPTURE DIED report, which would send a human chasing a dead device.
  if grep -q "CAPTURE DIED" "$WORK/out.$sig" 2>/dev/null; then
    echo "FAIL - SIG$sig reported CAPTURE DIED for a deliberate stop"
    fail=1
  else
    echo "ok - SIG$sig exited without a false CAPTURE DIED report"
  fi

  # ...and it must SAY it stopped. This is the assertion that keeps the rest
  # of this test honest: it can only pass if the signal reached the real
  # python process AND the handler ran, so a mis-resolved pid (see above) can
  # no longer make the whole file pass while proving nothing. It is also the
  # observable behaviour that is genuinely new here -- on this console the
  # difference between "stopped on purpose" and "went silently deaf" is the
  # single most expensive ambiguity a human hits.
  if grep -q "stopped; released" "$WORK/out.$sig" 2>/dev/null; then
    echo "ok - SIG$sig announced the deliberate stop on the pane"
  else
    echo "FAIL - SIG$sig died without announcing it (handler never ran, or the wrong pid was signalled)"
    fail=1
  fi

  # A stop asked for by a human/supervisor is a success, not a failure.
  if [ "${py_rc:-0}" -eq 0 ]; then
    echo "ok - SIG$sig exited 0 (deliberate stop is not an error)"
  else
    echo "FAIL - SIG$sig exited $py_rc; a supervisor would read a clean stop as a crash"
    fail=1
  fi

  kill -9 "$py_pid" 2>/dev/null
done

# --- the real `tmux kill-window` shape: the pty goes away FIRST -------------
# The loop above signals a process whose stdout is a plain file, which is the
# `systemctl stop` / `pkill` case. It is NOT the tmux case, and the difference
# is load-bearing: tmux delivers SIGHUP *because* it destroyed the pty, so by
#   [rest: vault:crt/header-archaeology-20260817.md]
cat > "$WORK/pty_hangup.py" <<'PY'
import os, pty, sys, time
bindir, fakebin = sys.argv[1], sys.argv[2]
pid, fd = pty.fork()
if pid == 0:
    os.environ.update(PATH=fakebin + ":" + os.environ["PATH"],
                      CRT_STT_SINK="stdout", CRT_AUDIO_DEV="plughw:9,9")
    os.execvp("python3", ["python3", "-u", bindir + "/crt-stt-solo.py"])
time.sleep(2.5)
os.close(fd)        # pane destroyed; the kernel hangs up the fg process group
_, status = os.waitpid(pid, 0)
print(os.WEXITSTATUS(status) if os.WIFEXITED(status)
      else 128 + os.WTERMSIG(status))
PY
pty_rc="$(python3 "$WORK/pty_hangup.py" "$BIN_DIR" "$FAKE_BIN" 2>/dev/null | tail -1)"
if [ "$pty_rc" = "0" ]; then
  echo "ok - a destroyed pty (tmux kill-window) still exits 0, not EIO-on-print"
else
  echo "FAIL - pty hangup exited $pty_rc; the farewell print raised on a dead tty"
  fail=1
fi

exit "$fail"
