#!/usr/bin/env bash
# Runs the whole offline test suite. No VM/hardware/network needed --
# these are exactly the checks that CAN run before ever touching crt-vm.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fail=0

# Marker so the secretary's "run the tests" meta-test (test_secretary.py's
# test_runs_real_suite_and_reports_green) can tell it's running INSIDE this
# suite and skip re-invoking it -- otherwise it shells back out to this
# script and recurses without bound. Standalone (python3 test_secretary.py)
# the var is unset, so that test still runs for real exactly once.
export CRT_TEST_SUITE_RUNNING=1

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
bash "$DIR/test_stt_feed_gate_flag.sh" || fail=1
echo

echo "== crt-audio-doctor.sh LIVE/DEAD verdicts =="
bash "$DIR/test_audio_doctor.sh" || fail=1
echo

echo "== crt-lib-audio-device.sh by-name device resolution (bash tools) =="
bash "$DIR/test_audio_device_lib.sh" || fail=1
echo

echo "== crt-pager.py =="
python3 "$DIR/test_pager.py" || fail=1
echo

echo "== crt-monologue.py (the actually-live 'mono' window script) =="
python3 "$DIR/test_monologue_py.py" || fail=1
echo

echo "== crt-predict.py =="
python3 "$DIR/test_predict.py" || fail=1
echo

echo "== crt-stt-solo.py STT gate =="
python3 "$DIR/test_stt_gate.py" || fail=1
echo

echo "== crt-stt-solo.py secretary sink =="
python3 -m unittest discover -s "$DIR" -p "test_stt_secretary_sink.py" -v 2>&1 | tail -5 || fail=1
echo

echo "== crt-stt-solo.py helper functions (fixups/classify/hud/ctl-line) =="
python3 "$DIR/test_stt_solo_helpers.py" || fail=1
echo

echo "== crt-stt-solo.py capture device by name =="
python3 "$DIR/test_capture_device.py" || fail=1
bash "$DIR/test_capture_death_loud.sh" || fail=1
echo

echo "== crt-stt-solo.py excises a duck that lands mid-utterance =="
bash "$DIR/test_duck_midutterance_excision.sh" || fail=1
echo

echo "== crt-stt-solo.py keeps ducked audio out of the pre-roll too =="
bash "$DIR/test_duck_preroll_leak.sh" || fail=1
echo

echo "== crt-stt-solo.py releases the mic when stopped =="
bash "$DIR/test_capture_release_on_signal.sh" || fail=1
echo

echo "== crt-book-game.py =="
python3 -m unittest discover -s "$DIR" -p "test_book_game.py" -v 2>&1 | tail -5 || fail=1
echo

echo "== crt-book-idle-bait.py =="
python3 -m unittest discover -s "$DIR" -p "test_book_idle_bait.py" -v 2>&1 | tail -5 || fail=1
echo

echo "== crt-book-console.py =="
python3 -m unittest discover -s "$DIR" -p "test_book_console.py" -v 2>&1 | tail -5 || fail=1
echo

echo "== crt-claude-bridge.py =="
python3 "$DIR/test_claude_bridge.py" || fail=1
echo

# 2026-07-25: this file existed but nothing ran it, so the CAPTURE/SEND
# protocol of the bridge the live brain-on-mandark path depends on had zero
# coverage in the suite. See the manifest check at the bottom.
echo "== crt-remote-claude-bridge.py (mandark brain bridge protocol) =="
python3 "$DIR/test_remote_claude_bridge.py" || fail=1
echo

# 2026-07-25: likewise orphaned.
echo "== crt-stt-solo.py confidence scoring =="
python3 "$DIR/test_stt_confidence.py" || fail=1
echo

# 2026-07-25 (sixth cycle): the reply channel this tier gets its only human
# feedback through. Includes the enforcement pass over .reports-fallback/, so
# a cycle that nests an earlier report inside the current one fails here
# instead of silently costing the next cycle's feedback.
echo "== crt-report-lint.py (a report an inline reply can anchor to) =="
python3 "$DIR/test_report_lint.py" || fail=1
echo

echo "== crt-calibrate.py (auto safe-area + conf round-trip) =="
python3 "$DIR/test_calibrate.py" || fail=1
echo

echo "== crt-book-answer-listen.py =="
python3 -m unittest discover -s "$DIR" -p "test_book_answer_listen.py" -v 2>&1 | tail -5 || fail=1
echo

echo "== crt-book-game-stats.py =="
python3 -m unittest discover -s "$DIR" -p "test_book_game_stats.py" -v 2>&1 | tail -5 || fail=1
echo

echo "== crt-speculate.py =="
python3 -m unittest discover -s "$DIR" -p "test_speculate.py" -v 2>&1 | tail -5 || fail=1
echo

echo "== crt-media-player.py =="
python3 -m unittest discover -s "$DIR" -p "test_media_player.py" -v 2>&1 | tail -5 || fail=1
echo

echo "== Book Game full-funnel integration =="
python3 -m unittest discover -s "$DIR" -p "test_book_game_integration.py" -v 2>&1 | tail -5 || fail=1
echo

echo "== crt-book-catalog.py =="
python3 -m unittest discover -s "$DIR" -p "test_book_catalog.py" -v 2>&1 | tail -5 || fail=1
echo

echo "== crt-wake-pool.py (fuzzy wake-word pool, pulled from crt-vm) =="
python3 -m unittest discover -s "$DIR" -p "test_wake_pool.py" -v 2>&1 | tail -5 || fail=1
echo

echo "== crt-wake-arm.py (arm-window state machine, 2026-07-23) =="
python3 -m unittest discover -s "$DIR" -p "test_wake_arm.py" -v 2>&1 | tail -5 || fail=1
echo

echo "== crt-wake-pool-tally.py (near-miss tally, pulled from crt-vm) =="
python3 -m unittest discover -s "$DIR" -p "test_wake_pool_tally.py" -v 2>&1 | tail -5 || fail=1
echo

echo "== crt-wake-judge.py (autonomous wake-word tuning judge, pulled from crt-vm) =="
python3 -m unittest discover -s "$DIR" -p "test_wake_judge.py" -v 2>&1 | tail -5 || fail=1
echo

echo "== crt-attach-ssh-bridge.sh (pulled from crt-vm) =="
bash "$DIR/test_attach_ssh_bridge.sh" || fail=1
echo


echo "== crt-window-switcher.py =="
python3 -m unittest discover -s "$DIR" -p "test_window_switcher.py" -v 2>&1 | tail -5 || fail=1
echo

echo "== crt-stt-training-merge.py =="
python3 -m unittest discover -s "$DIR" -p "test_stt_training_merge.py" -v 2>&1 | tail -5 || fail=1
echo

echo "== crt-secretary.py playbooks =="
if [ "${CRT_SKIP_SECRETARY_TESTS:-0}" = "0" ]; then
  python3 "$DIR/test_secretary.py" || fail=1
fi
echo

echo "== crt-calibrate-display.py =="
python3 "$DIR/test_calibrate_display.py" || fail=1
echo

echo "== crt-present-morning-report.py =="
python3 "$DIR/test_present_morning_report.py" || fail=1
echo

echo "== crt-tts.py prosody =="
python3 "$DIR/test_tts_prosody.py" || fail=1
echo

echo "== sideband wiring (stt-solo state + tts duck) =="
python3 "$DIR/test_sideband_wiring.py" || fail=1
echo

echo "== earcon sideband duck =="
bash "$DIR/test_earcon_sideband_duck.sh" || fail=1
echo

echo "== earcon/tts handset capture duck =="
bash "$DIR/test_earcon_capture_duck.sh" || fail=1
python3 "$DIR/test_tts_capture_duck.py" || fail=1
echo

echo "== capture duck released when its producer is killed =="
bash "$DIR/test_capture_duck_signal_safety.sh" || fail=1
echo

echo "== crt-mandark.sh on/off/status toggle =="
bash "$DIR/test_mandark_toggle.sh" || fail=1
echo

echo "== crt-mandark-serve.sh status/args (non-destructive) =="
bash "$DIR/test_mandark_serve.sh" || fail=1
echo

echo "== crt-wake-router.py brain decision =="
python3 "$DIR/test_wake_router.py" || fail=1
echo

echo "== crt-screensaver.py potato art =="
python3 "$DIR/test_screensaver.py" || fail=1
echo

echo "== crt-console.sh Book Game funnel windows (both layouts) =="
bash "$DIR/test_console_book_game_layout.sh" || fail=1
echo

echo "== crt-console.sh CRT_CTL_FILE export =="
bash "$DIR/test_console_ctl_env_export.sh" || fail=1
echo

# Manifest check (2026-07-25). Every test file in this directory must be named
# above, and every name above must exist. Both directions had really drifted:
#
#   - test_audio_doctor.sh and test_mic_footer.sh were NAMED but absent, left
#     behind by 38607bd (one of the four potato cherry-picks, which brought the
#     runner's references across without the files). Each sat inside an
#     `if [ -f ... ]; then` guard, so the suite printed a header claiming that
#     coverage, ran nothing, and reported ALL GREEN. Those guards are gone --
#     every test is invoked unconditionally now, so a missing file fails loud.
#   - test_remote_claude_bridge.py and test_stt_confidence.py EXISTED but were
#     never named, so 18 passing tests -- including the only coverage of the
#     mandark brain bridge -- were not in the suite at all.
#
# Same family as the three `command -v sox || skip` no-ops found the cycle
# before: a check that quietly does nothing reads exactly like a check that
# passed. This is the mechanical enforcement, not a comment asking the next
# person to remember.
echo "== test manifest (every test file named, every named file present) =="
mfail=0
# Comment lines are stripped first: the writeup above names both of the files
# that went missing, and matching those would make this check fail on its own
# explanation. Only real invocations count.
invocations="$(grep -v '^[[:space:]]*#' "$DIR/run_tests.sh")"
for f in "$DIR"/test_*.sh "$DIR"/test_*.py; do
  base="$(basename "$f")"
  if ! printf '%s\n' "$invocations" | grep -q "$base"; then
    echo "FAIL - $base exists but run_tests.sh never runs it"
    mfail=1
  fi
done
for base in $(printf '%s\n' "$invocations" \
                | grep -o 'test_[a-z_0-9]*\.\(sh\|py\)' | sort -u); do
  if [ ! -f "$DIR/$base" ]; then
    echo "FAIL - run_tests.sh names $base, which does not exist"
    mfail=1
  fi
done
if [ "$mfail" -eq 0 ]; then
  echo "ok - test manifest consistent both ways"
else
  fail=1
fi
echo

if [ "$fail" -eq 0 ]; then
  echo "ALL GREEN"
else
  echo "SOMETHING FAILED"
fi
exit "$fail"
