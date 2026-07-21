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

echo "== stt-feed.sh CRT_STT_GATE opt-in gate =="
if [ -f "$DIR/test_stt_feed_gate_flag.sh" ]; then
  bash "$DIR/test_stt_feed_gate_flag.sh" || fail=1
fi
echo

echo "== crt-pager.py =="
python3 "$DIR/test_pager.py" || fail=1
echo

echo "== crt-predict.py =="
if [ -f "$DIR/test_predict.py" ]; then
  python3 "$DIR/test_predict.py" || fail=1
fi
echo

echo "== crt-stt-solo.py STT gate =="
if [ -f "$DIR/test_stt_gate.py" ]; then
  python3 "$DIR/test_stt_gate.py" || fail=1
fi
echo

echo "== crt-stt-solo.py secretary sink =="
if [ -f "$DIR/test_stt_secretary_sink.py" ]; then
  python3 -m unittest discover -s "$DIR" -p "test_stt_secretary_sink.py" -v 2>&1 | tail -5 || fail=1
fi
echo

echo "== crt-book-game.py =="
if [ -f "$DIR/test_book_game.py" ]; then
  python3 -m unittest discover -s "$DIR" -p "test_book_game.py" -v 2>&1 | tail -5 || fail=1
fi
echo

echo "== crt-book-idle-bait.py =="
if [ -f "$DIR/test_book_idle_bait.py" ]; then
  python3 -m unittest discover -s "$DIR" -p "test_book_idle_bait.py" -v 2>&1 | tail -5 || fail=1
fi
echo

echo "== crt-book-console.py =="
if [ -f "$DIR/test_book_console.py" ]; then
  python3 -m unittest discover -s "$DIR" -p "test_book_console.py" -v 2>&1 | tail -5 || fail=1
fi
echo

echo "== crt-book-answer-listen.py =="
if [ -f "$DIR/test_book_answer_listen.py" ]; then
  python3 -m unittest discover -s "$DIR" -p "test_book_answer_listen.py" -v 2>&1 | tail -5 || fail=1
fi
echo

echo "== crt-book-game-stats.py =="
if [ -f "$DIR/test_book_game_stats.py" ]; then
  python3 -m unittest discover -s "$DIR" -p "test_book_game_stats.py" -v 2>&1 | tail -5 || fail=1
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
echo

echo "== sideband wiring (stt-solo state + tts duck) =="
if [ -f "$DIR/test_sideband_wiring.py" ]; then
  python3 "$DIR/test_sideband_wiring.py" || fail=1
fi
echo

echo "== earcon sideband duck =="
bash "$DIR/test_earcon_sideband_duck.sh" || fail=1
echo

if [ "$fail" -eq 0 ]; then
  echo "ALL GREEN"
else
  echo "SOMETHING FAILED"
fi
exit "$fail"
