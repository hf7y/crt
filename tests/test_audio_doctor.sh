#!/usr/bin/env bash
# Offline test for bin/crt-audio-doctor.sh -- the capture-liveness instrument
# AUDIO-DEBUG.md calls Approach D.
#
# Why this file exists (2026-07-25): tests/run_tests.sh has printed the header
#   [rest: vault:crt/header-archaeology-20260817.md]
set -uo pipefail
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)"
fail=0

FAKE_BIN="$(mktemp -d)"
WORK="$(mktemp -d)"
trap 'rm -rf "$FAKE_BIN" "$WORK"' EXIT

# Fake capture device. CRT_FAKE_AMP picks what the mic "hears"; CRT_FAKE_FAIL
# makes arecord die with no output at all, the way a device already held by
# another reader does.
cat > "$FAKE_BIN/arecord" <<'EOF'
#!/usr/bin/env python3
import array, math, os, sys

if "-l" in sys.argv:
    print("**** List of CAPTURE Hardware Devices ****")
    print("card 1: Device [KT USB Audio], device 0: USB Audio [USB Audio]")
    print("  Subdevices: 1/1")
    sys.exit(0)

with open(os.environ["CRT_FAKE_ARGV"], "w") as f:
    f.write(" ".join(sys.argv[1:]) + "\n")

if os.environ.get("CRT_FAKE_FAIL") == "1":
    sys.stderr.write("audio open error: Device or resource busy\n")
    sys.exit(1)

amp = float(os.environ.get("CRT_FAKE_AMP", "0"))
secs = float(sys.argv[sys.argv.index("-d") + 1])
n = int(16000 * secs)
a = array.array('h', (int(amp * 32767 * math.sin(2 * math.pi * 440 * i / 16000))
                      for i in range(n)))
sys.stdout.buffer.write(a.tobytes())
EOF
chmod +x "$FAKE_BIN/arecord"

# Deterministic mixer, so this test reads the same on a box that has a real
# amixer with real cards as on one that has none.
cat > "$FAKE_BIN/amixer" <<'EOF'
#!/usr/bin/env bash
echo "  Item0: 'Mic'"
echo "  Front Left: Capture 31 [80%] [on]"
EOF
chmod +x "$FAKE_BIN/amixer"

run_doctor() {   # run_doctor <amp> <fail> [args...]
  local amp="$1" ff="$2"; shift 2
  CRT_FAKE_AMP="$amp" CRT_FAKE_FAIL="$ff" CRT_FAKE_ARGV="$WORK/argv" \
  CRT_DOC_SECS=1 HOME="$WORK" PATH="$FAKE_BIN:$PATH" \
    bash "$BIN_DIR/crt-audio-doctor.sh" "$@" >"$WORK/out" 2>"$WORK/err"
  echo "$?"
}

# 1. A mic delivering real signal is LIVE, exit 0.
rc="$(run_doctor 0.5 0 check)"
if [ "$rc" = "0" ] && grep -q "verdict: LIVE" "$WORK/out"; then
  echo "ok - a mic delivering signal reads LIVE (exit 0)"
else
  echo "FAIL - live mic did not read LIVE (exit $rc)"; sed -n 1,15p "$WORK/out" "$WORK/err"; fail=1
fi

# 2. A flatlined mic is DEAD/STALE with a NONZERO exit -- the exit code is the
#    point, since that is what a watchdog/timer reads.
rc="$(run_doctor 0 0 check)"
if [ "$rc" != "0" ] && grep -q "verdict: DEAD/STALE" "$WORK/out"; then
  echo "ok - a flatlined mic reads DEAD/STALE and exits nonzero ($rc)"
else
  echo "FAIL - flatlined mic did not report DEAD/STALE + nonzero (exit $rc)"; sed -n 1,15p "$WORK/out"; fail=1
fi

# 3. The case this instrument exists for: arecord itself failing (device busy,
#    held by the sole-reader crt-stt-solo.py) delivers NO bytes at all. That
#    must read DEAD, not LIVE -- an empty read scoring as healthy is exactly
#    the silent-success failure this project keeps hitting.
rc="$(run_doctor 0.5 1 check)"
if [ "$rc" != "0" ] && grep -q "verdict: DEAD/STALE" "$WORK/out"; then
  echo "ok - a busy/failing capture device reads DEAD/STALE, not LIVE ($rc)"
else
  echo "FAIL - a failing arecord did not read DEAD/STALE (exit $rc)"; sed -n 1,15p "$WORK/out"; fail=1
fi

# 4. Device resolution: with nothing pinned it must resolve BY NAME off
#    `arecord -l` (card 1 here), never fall back to a hardcoded card 0 -- the
#    bug 108406f fixed, where this defaulted to potato's USB mic but mandark's
#    own onboard card.
rc="$(run_doctor 0.5 0 check)"
if grep -q -- "-D plughw:1,0" "$WORK/argv"; then
  echo "ok - capture device resolved by name to card 1, not hardcoded card 0"
else
  echo "FAIL - did not resolve by name; sampled with: $(cat "$WORK/argv")"; fail=1
fi
if grep -q "device : plughw:1,0" "$WORK/out"; then
  echo "ok - the report names the device it actually sampled"
else
  echo "FAIL - report does not name the resolved device"; sed -n 1,10p "$WORK/out"; fail=1
fi

# 5. An explicit CRT_DOC_DEV is a hard override of the name resolution (the
#    "never remove the manual escape hatch" rule this project applies to every
#    automatic device path).
CRT_FAKE_AMP=0.5 CRT_FAKE_FAIL=0 CRT_FAKE_ARGV="$WORK/argv" \
CRT_DOC_SECS=1 CRT_DOC_DEV=crtmic HOME="$WORK" PATH="$FAKE_BIN:$PATH" \
  bash "$BIN_DIR/crt-audio-doctor.sh" check >"$WORK/out" 2>"$WORK/err"
if grep -q -- "-D crtmic" "$WORK/argv"; then
  echo "ok - CRT_DOC_DEV overrides name resolution"
else
  echo "FAIL - CRT_DOC_DEV was ignored; sampled with: $(cat "$WORK/argv")"; fail=1
fi

# 6. CRT_DOC_DEAD_PEAK is the knob that decides the verdict, so a signal that
#    reads LIVE at the default must read DEAD once the bar is raised past it.
CRT_FAKE_AMP=0.5 CRT_FAKE_FAIL=0 CRT_FAKE_ARGV="$WORK/argv" \
CRT_DOC_SECS=1 CRT_DOC_DEAD_PEAK=0.9 HOME="$WORK" PATH="$FAKE_BIN:$PATH" \
  bash "$BIN_DIR/crt-audio-doctor.sh" check >"$WORK/out" 2>"$WORK/err"
if grep -q "verdict: DEAD/STALE" "$WORK/out"; then
  echo "ok - CRT_DOC_DEAD_PEAK moves the LIVE/DEAD boundary"
else
  echo "FAIL - raising CRT_DOC_DEAD_PEAK past the signal still read LIVE"; sed -n 1,10p "$WORK/out"; fail=1
fi

# 7. An unknown subcommand is a usage error (exit 2), not a silent success.
rc="$(run_doctor 0.5 0 wat)"
if [ "$rc" = "2" ] && grep -q "usage:" "$WORK/err"; then
  echo "ok - an unknown subcommand exits 2 with usage"
else
  echo "FAIL - unknown subcommand did not exit 2 with usage (exit $rc)"; fail=1
fi

exit "$fail"
