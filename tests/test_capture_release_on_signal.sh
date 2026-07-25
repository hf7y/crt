#!/usr/bin/env bash
# Offline test: when crt-stt-solo.py is stopped, it must RELEASE the mic --
# i.e. its arecord child must actually be gone, not merely signalled.
#
# READ THIS BEFORE TRUSTING IT -- the four assertions per signal are not all
# the same strength, and it matters which is which:
#
#   "released the capture device"  -- a REGRESSION GUARD. It passed before the
#       2026-07-25 signal handlers existed too; the mic was never actually
#       leaking (see below). Pinned because losing it would be expensive.
#   "no false CAPTURE DIED"        -- same: a guard on behaviour that was
#       already correct.
#   "announced the deliberate stop" and "exited 0" -- REAL WITNESSES. These
#       fail against the pre-2026-07-25 code, because an untrapped SIGTERM/
#       SIGHUP killed the process outright: no message, and an exit status of
#       128+signum that a supervisor reads as a crash.
#
# The story, recorded so nobody re-derives it. crt-stt-solo.py is the
# documented SOLE reader of the capture device; a leftover arecord holding
# that device would be serious, because capture death now exits 3 (db39b61),
# so an orphan would turn one restart into a supervisor restart LOOP blocked
# by the corpse of the previous run -- "second reader starving the first",
# with the second reader being our own child. Python does skip finally: on an
# untrapped SIGTERM/SIGHUP (verified the same day; it runs it on SIGINT only),
# so the bare `finally: proc.terminate()` really was never reached.
#
# It still did not leak, for a reason that has nothing to do with the handler:
# when this process exits, the read end of arecord's stdout pipe closes and
# arecord dies of SIGPIPE on its next write. Measured both ways -- the child
# was gone within ~3s with or without the fix. (An earlier probe that appeared
# to show an orphan was signalling `setsid`'s already-exited pid instead of
# python's, so nothing had been killed at all. Hence the pgrep below.)
#
# Each signal goes to the python process ALONE (setsid puts it in its own
# process group), which is what `pkill -f crt-stt-solo.py`, `systemctl stop`,
# and a supervisor restart all do. That isolation is deliberate: a signal
# broadcast to the whole group would kill arecord for us and prove nothing.
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

exit "$fail"
