#!/usr/bin/env bash
# Runs the whole offline test suite. No VM/hardware/network needed --
# these are exactly the checks that CAN run before ever touching crt-vm.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fail=0

echo "== shell syntax =="
bash "$DIR/test_shell_syntax.sh" || fail=1
echo

echo "== crt-monologue.sh width resolution =="
bash "$DIR/test_monologue_width.sh" || fail=1
echo

echo "== crt-monologue.sh overscan margin =="
bash "$DIR/test_monologue_margin.sh" || fail=1
echo

echo "== hookswitch debounce =="
bash "$DIR/test_hookswitch_debounce.sh" || fail=1
echo

echo "== sideband ambient tone =="
bash "$DIR/test_sideband.sh" || fail=1
echo

echo "== idle-teaser screensaver gate =="
bash "$DIR/test_idle_teaser.sh" || fail=1
echo

echo "== stt-feed.sh CRT_SECRETARY opt-in gate =="
bash "$DIR/test_stt_feed_secretary_flag.sh" || fail=1
echo

echo "== crt-pager.py =="
python3 "$DIR/test_pager.py" || fail=1
echo

echo "== crt-predict.py =="
if [ -f "$DIR/test_predict.py" ]; then
  python3 "$DIR/test_predict.py" || fail=1
fi
echo

echo "== crt-secretary.py playbooks =="
if [ -f "$DIR/test_secretary.py" ] && [ "${CRT_SKIP_SECRETARY_TESTS:-0}" = "0" ]; then
  python3 "$DIR/test_secretary.py" || fail=1
fi
echo

echo "== crt-calibrate-display.py =="
if [ -f "$DIR/test_calibrate_display.py" ]; then
  python3 "$DIR/test_calibrate_display.py" || fail=1
fi
echo

echo "== crt-present-morning-report.py =="
if [ -f "$DIR/test_present_morning_report.py" ]; then
  python3 "$DIR/test_present_morning_report.py" || fail=1
fi
echo

echo "== crt-tts.py prosody =="
if [ -f "$DIR/test_tts_prosody.py" ]; then
  python3 "$DIR/test_tts_prosody.py" || fail=1
fi

if [ "$fail" -eq 0 ]; then
  echo "ALL GREEN"
else
  echo "SOMETHING FAILED"
fi
exit "$fail"
