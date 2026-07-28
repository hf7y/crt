#!/usr/bin/env bash
# Offline test for bin/crt-stt-supervisor.sh (2026-07-28): the wrapper
# that restarts crt-stt-solo.py when it exits, alarms every time, and
# resets backoff after a healthy stretch (see that script's own header
# for why -- a live capture crash tonight left the console silently deaf
# until someone SSH'd in and noticed).
set -uo pipefail
REAL_BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)"
fail=0

FAKE_BIN="$(mktemp -d)"
WORK="$(mktemp -d)"
trap 'rm -rf "$FAKE_BIN" "$WORK"' EXIT

# Run the REAL supervisor script from a fake bin dir alongside fakes of
# the two things it launches -- BIN_DIR resolves from $BASH_SOURCE, so
# copying it in is enough to redirect both launches without touching the
# script under test.
cp "$REAL_BIN_DIR/crt-stt-supervisor.sh" "$FAKE_BIN/crt-stt-supervisor.sh"
chmod +x "$FAKE_BIN/crt-stt-supervisor.sh"

# A fake crt-stt-solo.py that exits immediately every time it's launched.
cat > "$FAKE_BIN/crt-stt-solo.py" <<EOF
#!/usr/bin/env python3
import sys
with open("$WORK/runs", "a") as f:
    f.write("run\n")
sys.exit(1)
EOF
chmod +x "$FAKE_BIN/crt-stt-solo.py"

# A fake crt-earcon.sh that counts "alarm" calls instead of touching
# real audio hardware.
cat > "$FAKE_BIN/crt-earcon.sh" <<EOF
#!/usr/bin/env bash
if [ "\$1" = "alarm" ]; then
  echo "alarm \$*" >> "$WORK/alarms"
fi
exit 0
EOF
chmod +x "$FAKE_BIN/crt-earcon.sh"

echo "== crashes repeatedly: supervisor keeps restarting and alarms every time =="
HOME="$WORK" CRT_STT_SUP_MIN_HEALTHY_SECS=9999 CRT_STT_SUP_BACKOFF_CAP_SECS=0 \
  timeout 2 "$FAKE_BIN/crt-stt-supervisor.sh" >/dev/null 2>&1 || true

runs=$(wc -l < "$WORK/runs" 2>/dev/null || echo 0)
alarms=$(wc -l < "$WORK/alarms" 2>/dev/null || echo 0)

if [ "$runs" -lt 2 ]; then
  echo "FAIL - expected the fake crt-stt-solo.py to be relaunched at least twice in 2s, got $runs"
  fail=1
else
  echo "PASS - relaunched $runs times in 2s"
fi

if [ "$alarms" -lt 2 ]; then
  echo "FAIL - expected at least 2 alarm calls, got $alarms"
  fail=1
else
  echo "PASS - fired $alarms alarms, one per crash ($alarms alarms for $runs crashes)"
fi

# Allow the LAST cycle to be missing its alarm -- `timeout` can kill the
# script between the crash being logged and the alarm firing (both are
# real, just racing the cutoff), not a real gap in every-crash coverage.
missing=$((runs - alarms))
if [ "$missing" -gt 1 ]; then
  echo "FAIL - expected at most 1 crash short an alarm (a timeout-boundary artifact), got $runs crashes but only $alarms alarms"
  fail=1
else
  echo "PASS - every crash but at most the last (timeout-boundary) one alarmed"
fi

if [ "$fail" = 1 ]; then
  echo "SOMETHING FAILED"
  exit 1
fi
echo "all crt-stt-supervisor.sh checks passed"

echo
echo "== backoff actually slows retries down (vs cap=0 above) =="
: > "$WORK/runs"
: > "$WORK/alarms"
HOME="$WORK" CRT_STT_SUP_MIN_HEALTHY_SECS=9999 CRT_STT_SUP_BACKOFF_CAP_SECS=30 \
  timeout 4 "$FAKE_BIN/crt-stt-supervisor.sh" >/dev/null 2>&1 || true

backoff_runs=$(wc -l < "$WORK/runs" 2>/dev/null || echo 0)
# crashes 1,2 instant; 3->1s; 4->2s; 5->4s -- by 4s wall clock, expect
# roughly 5-6 runs, nowhere near the ~20+ a cap=0 run would rack up in
# the same window. Loose upper bound, not an exact count -- timing-based.
if [ "$backoff_runs" -gt 10 ]; then
  echo "FAIL - expected backoff to meaningfully slow retries (<=10 runs in 4s), got $backoff_runs"
  fail=1
elif [ "$backoff_runs" -lt 2 ]; then
  echo "FAIL - expected at least the instant-retry runs to happen, got $backoff_runs"
  fail=1
else
  echo "PASS - backoff kept retries bounded ($backoff_runs runs in 4s, vs no-backoff's much higher rate)"
fi

if [ "$fail" = 1 ]; then
  echo "SOMETHING FAILED"
  exit 1
fi
echo "all crt-stt-supervisor.sh checks passed"
