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

# Nothing in this suite may touch the LIVE console's state (2026-07-25).
# Measured, not assumed: five test files were appending to the real
# ~/.crt/ctl -- the capture-duck control channel a RUNNING crt-stt-solo.py
# reads live -- and stamping the real ~/.crt/claude-window-active.state,
#   [rest: vault:crt/header-archaeology-20260817.md]
CRT_TEST_STATE_DIR="$(mktemp -d)"
export CRT_CTL_FILE="$CRT_TEST_STATE_DIR/ctl"
export CRT_CLAUDE_ACTIVE_STATE="$CRT_TEST_STATE_DIR/claude-window-active.state"
export CRT_THOUGHT_LOG="$CRT_TEST_STATE_DIR/thoughts.log"
# TWO vars name that same file: crt-stt-solo.py's GATE_LOG and stt-feed.sh's
# both default to ~/.crt/thoughts.log under CRT_STT_GATE_LOG. Pinning
# CRT_THOUGHT_LOG alone left the gate-drop path still writing to the live
# one -- found by the guard below on its first run, which is the argument
# for having it. (bin/crt-bell-test.sh now honors those vars too -- crt#149
# -- but it's a live-audio watch loop with no exit, so it's still not run here.)
export CRT_STT_GATE_LOG="$CRT_TEST_STATE_DIR/thoughts.log"
# Found by the guard below on its SECOND run (2026-07-25): a sixth live
# file. crt-idle-teaser.sh's chime() stamps the announce lock, which is the
# 15-minute rate limit it deliberately SHARES with crt-announce.sh's TV
# announcements -- so a suite run on potato silenced the console's next
# real chime and its next real announcement, both. Its seen-ledger is
# touched at source time by every case in that file.
export CRT_ANNOUNCE_LOCK="$CRT_TEST_STATE_DIR/announce.lastrun"
export CRT_IDLE_SEEN="$CRT_TEST_STATE_DIR/idle-bait.seen"
# A seventh (crt#34): crt-media-player.py's persisted playback state.
export CRT_MEDIA_STATE_FILE="$CRT_TEST_STATE_DIR/media-state"
trap 'rm -rf "$CRT_TEST_STATE_DIR"' EXIT

# ...and a guard, because pinning only covers the vars known TODAY and this
# is the third cycle to find this class. Snapshot the live state dir now,
# compare at the end, name whatever moved. Skipped (loudly) when a console
# is actually running on this box, since then ~/.crt changes for real
# reasons and nothing here could attribute them.
CRT_LIVE_STATE_DIR="${CRT_LIVE_STATE_DIR:-$HOME/.crt}"
snapshot_live_state() {
  find "$CRT_LIVE_STATE_DIR" -type f 2>/dev/null | sort | xargs -r md5sum 2>/dev/null
}
LIVE_STATE_BEFORE="$(snapshot_live_state)"

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

echo "== hookswitch gpio transport =="
bash "$DIR/test_hookswitch_gpio.sh" || fail=1
echo

echo "== sideband ambient tone =="
bash "$DIR/test_sideband.sh" || fail=1
echo

echo "== idle-teaser screensaver gate =="
bash "$DIR/test_idle_teaser.sh" || fail=1
echo

# 2026-07-25: CLAUDE.md cites test_book_game.py's palette check as the proof
# the CRT-safe color rule is "not just a comment" -- but that check reads
# five constants in one Python module, and crt-idle-teaser.sh had been
# putting bold red (31) on window 1 since the day it was written. This one
# reads every file in bin/ and tests/.
echo "== CRT-safe palette, whole tree (no 31/32/34/91/92/94) =="
bash "$DIR/test_crt_safe_colors.sh" || fail=1
echo

# 2026-07-25: crt-announce.sh had no test at all, and it writes the window
# crt-idle-teaser.sh's chime() rate-limits against. A failed announcement
# used to spend fifteen minutes of silence on BOTH channels.
echo "== crt-announce.sh shared rate-limit window =="
bash "$DIR/test_announce_rate_limit.sh" || fail=1
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

echo "== crt-stt-inbox.sh sweeps the inbox (ffmpeg/curl stubbed) =="
bash "$DIR/test_stt_inbox.sh" || fail=1
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

echo "== crt-stt-solo.py re-reads stt-fixups.json when it changes =="
python3 "$DIR/test_fixups_reload.py" 2>&1 | tail -3 || fail=1
echo

echo "== crt-stt-solo.py secretary sink =="
python3 -m unittest discover -s "$DIR" -p "test_stt_secretary_sink.py" -v 2>&1 | tail -5 || fail=1
echo

echo "== crt-stt-solo.py helper functions (fixups/classify/hud/ctl-line) =="
python3 "$DIR/test_stt_solo_helpers.py" || fail=1
echo

echo "== crt-stt-solo.py tells a dead recogniser apart from a silent room =="
python3 "$DIR/test_transcribe_failure.py" 2>&1 | tail -3 || fail=1
echo

echo "== crt-stt-solo.py capture backpressure (pipe depth + stale-backlog drain) =="
python3 "$DIR/test_capture_backpressure.py" 2>&1 | tail -3 || fail=1
bash "$DIR/test_capture_backlog_drain.sh" || fail=1
echo

echo "== crt-stt-solo.py capture device by name =="
python3 "$DIR/test_capture_device.py" || fail=1
bash "$DIR/test_capture_death_loud.sh" || fail=1
echo

echo "== the pane behind the idle face is not a brain (stt-solo + secretary) =="
python3 "$DIR/test_idle_face_is_not_a_brain.py" 2>&1 | tail -3 || fail=1
echo

echo "== a remote brain's reply reaches window 1, not just the earpiece =="
python3 "$DIR/test_reply_reaches_window_one.py" 2>&1 | tail -3 || fail=1
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

echo "== trivia-fact enrichment pipeline (2026-07-28) =="
python3 -m unittest discover -s "$DIR" -p "test_book_facts.py" -v 2>&1 | tail -5 || fail=1
echo

echo "== crt-book-idle-bait.py =="
python3 -m unittest discover -s "$DIR" -p "test_book_idle_bait.py" -v 2>&1 | tail -5 || fail=1
echo

echo "== crt-book-blurb.py (crt#122) =="
python3 -m unittest discover -s "$DIR" -p "test_book_blurb.py" -v 2>&1 | tail -5 || fail=1
echo

echo "== bibliothecaire bibquotes idle-bait integration (2026-07-28) =="
python3 -m unittest discover -s "$DIR" -p "test_bibquotes.py" -v 2>&1 | tail -5 || fail=1
echo

echo "== crt-book-console.py =="
python3 -m unittest discover -s "$DIR" -p "test_book_console.py" -v 2>&1 | tail -5 || fail=1
echo

echo "== crt-claude-bridge.py =="
python3 "$DIR/test_claude_bridge.py" || fail=1
echo

echo "== crt-secretary.py clean_claude_pane_reply() (TUI-chrome stripping) =="
python3 "$DIR/test_clean_claude_pane_reply.py" || fail=1
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
# feedback through. A cycle that nests an earlier report inside the current one
# fails here instead of silently costing the next cycle's feedback.
echo "== crt-report-lint.py (a report an inline reply can anchor to) =="
python3 "$DIR/test_report_lint.py" || fail=1
echo

echo "== crt-calibrate.py (auto safe-area + conf round-trip) =="
python3 "$DIR/test_calibrate.py" || fail=1
echo

echo "== crt-book-answer-listen.py =="
python3 -m unittest discover -s "$DIR" -p "test_book_answer_listen.py" -v 2>&1 | tail -5 || fail=1
echo

echo "== a re-scanned book can be answered again (2026-07-25) =="
python3 -m unittest discover -s "$DIR" -p "test_book_rescan_pending.py" -v 2>&1 | tail -5 || fail=1
echo

echo "== one scan is one graded round, not a 20s window (2026-07-25) =="
python3 -m unittest discover -s "$DIR" -p "test_book_answer_round_closes.py" -v 2>&1 | tail -5 || fail=1
echo

echo "== correct_stt is not a second copy of correct_content (2026-07-25) =="
python3 -m unittest discover -s "$DIR" -p "test_book_game_stt_axis.py" -v 2>&1 | tail -5 || fail=1
echo

echo "== a question for Claude is not a trivia answer (2026-07-25) =="
python3 -m unittest discover -s "$DIR" -p "test_book_answer_wake_word.py" -v 2>&1 | tail -5 || fail=1
echo

echo "== a sticky-conversation follow-up is not a trivia answer (2026-07-25) =="
python3 -m unittest discover -s "$DIR" -p "test_book_answer_arm_window.py" -v 2>&1 | tail -5 || fail=1
echo

echo "== crt_loop_guard.py (background windows survive one bad iteration) =="
python3 "$DIR/test_loop_guard.py" 2>&1 | tail -3 || fail=1
echo

echo "== crt_config.py (one answer for where stt-fixups.json is) =="
python3 "$DIR/test_config_fixups_path.py" 2>&1 | tail -3 || fail=1
echo

echo "== crt_fixups_store.py (one safe way to change stt-fixups.json) =="
python3 "$DIR/test_fixups_store.py" 2>&1 | tail -3 || fail=1
echo

echo "== the two stt-fixups.json writers do not erase each other =="
python3 "$DIR/test_fixups_two_writers.py" 2>&1 | tail -3 || fail=1
echo

echo "== log readers survive a torn byte (window 1 stays lit) =="
python3 "$DIR/test_log_reader_decoding.py" 2>&1 | tail -3 || fail=1
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

echo "== the arm window measures silence, not whisper round-trips (2026-07-29) =="
python3 -m unittest discover -s "$DIR" -p "test_wake_arm_clock_domain.py" -v 2>&1 | tail -5 || fail=1
echo

echo "== a re-wake starts a fresh session, through the live emit() path (2026-07-25) =="
python3 -m unittest discover -s "$DIR" -p "test_wake_rearm_ceiling.py" -v 2>&1 | tail -5 || fail=1
echo

echo "== crt-calibration-game.py (what the confirm prompt will accept, 2026-07-25) =="
python3 -m unittest discover -s "$DIR" -p "test_calibration_game.py" -v 2>&1 | tail -5 || fail=1
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

echo "== crt-window-switcher.py idle-face-aware return target (2026-07-28) =="
python3 "$DIR/test_window_switcher_idle_face.py" || fail=1
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

echo "== a console that cannot speak says so =="
python3 "$DIR/test_speech_failure_visible.py" || fail=1
echo

echo "== a ring nobody could hear is not an unanswered call =="
python3 "$DIR/test_ring_actually_rings.py" || fail=1
echo

echo "== loopback test: three verdicts, not two =="
python3 "$DIR/test_loopback_verdict.py" || fail=1
echo

echo "== an earcon that never sounded leaves a trace =="
python3 "$DIR/test_earcon_failure_is_visible.py" || fail=1
echo

echo "== an utterance nothing handled is not an utterance never made =="
python3 "$DIR/test_dispatch_failure_visible.py" || fail=1
echo

echo "== window 1 fits the pane it is actually in =="
python3 "$DIR/test_monologue_viewport.py" || fail=1
echo

echo "== an uncalibrated tube gets the safe margin, not zero =="
python3 "$DIR/test_pager.py" || fail=1
echo

echo "== a console that cannot transcribe says so once (crt#132) =="
bash "$DIR/test_console_selfcheck.sh" || fail=1
echo

echo "== capture duck released when its producer is killed =="
bash "$DIR/test_capture_duck_signal_safety.sh" || fail=1
echo

echo "== crt-stt-supervisor.sh restarts on crash, alarms every time, backs off (2026-07-28) =="
bash "$DIR/test_stt_supervisor.sh" || fail=1
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

echo "== SSH-direct brain (crt-brain-shell + transport selection) =="
python3 "$DIR/test_brain_ssh.py" || fail=1
echo

echo "== crt-screensaver.py potato art =="
python3 "$DIR/test_screensaver.py" || fail=1
echo

echo "== crt-screensaver.py dual-art alternation + sunset (2026-07-28) =="
python3 "$DIR/test_screensaver_art_rotation.py" || fail=1
echo

echo "== crt-screensaver.py overscan safe-margin enforcement (2026-07-28) =="
python3 "$DIR/test_screensaver_safe_margins.py" || fail=1
echo

echo "== crt-screensaver.py blink model, sleep/wake, color gradient (2026-07-28) =="
python3 "$DIR/test_screensaver_blink_sleep.py" || fail=1
echo

# 2026-07-25: the scanner types into whichever tmux window has FOCUS, and the
# idle-lean layout gives focus to the screensaver -- so the idle face had been
# eating every scan on potato. Both halves of the funnel's first link:
echo "== crt-screensaver.py forwards the scans that land on the idle face =="
python3 "$DIR/test_screensaver_forwards_scans.py" || fail=1
echo

# 2026-07-25 (eighteenth cycle): and the OTHER half of that same window. The
# idle-lean layout boots into the screensaver, so on potato this is the screen
# the tube actually holds -- and its caption was one fixed string in one fixed
# spot from boot to shutdown, measured in characters on a screen sold in
# columns, in a frame one line taller than the tube.
echo "== crt-screensaver.py's caption moves, and fits (running process) =="
python3 "$DIR/test_screensaver_caption_moves.py" || fail=1
echo

echo "== a scan reaches the tube (book window takes focus, hands it back) =="
python3 "$DIR/test_scan_reaches_the_tube.py" || fail=1
echo

# 2026-07-25: crt-console.sh builds every window detached (tmux sizes those
# 80x24) and attaches last, so a window that measures once is wrong forever.
# The screensaver and window 1 were already fixed; the window that draws the
# question was not.
echo "== the book window measures the tube it draws on (pty resize) =="
python3 "$DIR/test_book_console_size.py" || fail=1
echo

echo "== the book window's overscan safe-margin enforcement (2026-07-28) =="
python3 "$DIR/test_book_console_safe_margins.py" || fail=1
echo

# 2026-07-25 (seventeenth cycle): render_idle_screen() moves its caption and
# swaps its text on every call, and main() called it once. The funnel's first
# link -- the screen that talks someone into scanning a book -- was a still
# frame from boot until somebody scanned one.
echo "== the idle screen redraws itself (pty, nobody at the console) =="
python3 "$DIR/test_book_idle_screen_moves.py" || fail=1
echo

# 2026-07-25 (seventeenth cycle): the same caption, measured in characters on
# a screen sold in columns, and cut where the budget ran out -- so the kaomoji
# line was drawn 42 columns into a 40-column pane, and four of six enticements
# lost the word "scan".
echo "== the idle caption fits the tube and still asks for a book =="
python3 "$DIR/test_idle_caption_fits.py" || fail=1
echo

echo "== crt-console.sh Book Game funnel windows (both layouts) =="
bash "$DIR/test_console_book_game_layout.sh" || fail=1
echo

echo "== crt-console.sh CRT_CTL_FILE export =="
bash "$DIR/test_console_ctl_env_export.sh" || fail=1
echo

echo "== console config comes from ~/.crt, not a login shell =="
bash "$DIR/test_console_conf.sh" || fail=1
echo

echo "== brain starts with permissions bypassed, and parks are detected =="
bash "$DIR/test_brain_session_bypass.sh" || fail=1
echo

echo "== ecosim cast sink: truncates loudly, counts what it drops =="
python3 "$DIR/test_cast_sink.py" || fail=1
echo

echo "== zaxon-watch guards (the rules that used to be README prose) =="
bash "$DIR/test_zaxon_watch_guards.sh" || fail=1
echo

echo "== zaxon-autoupdate rollback (crt#75) =="
bash "$DIR/test_zaxon_autoupdate_rollback.sh" || fail=1
echo

echo "== dexter vendored-unit check: a vendored --install unit that was never installed (crt#105) =="
bash "$DIR/test_dexter_vendored_units_check.sh" || fail=1
echo

echo "== zaxon status collector verdict ladder =="
python3 -m unittest discover -s "$DIR" -p "test_zaxon_status_collect.py" -v 2>&1 | tail -5 || fail=1
echo

echo "== zaxon relay question queue (crt#67) =="
python3 -m unittest discover -s "$DIR" -p "test_zaxon_relay_queue.py" -v 2>&1 | tail -20 || fail=1
echo

# Named, not globbed: the manifest check below matches basenames literally, so
# a glob here would read as "test_zaxon_relay_watcher.py is never run".
echo "== zaxon relay watcher: a voice note it could not hear is not an answer =="
python3 -m unittest discover -s "$DIR" -p "test_zaxon_relay_watcher.py" -v 2>&1 | tail -15 || fail=1
echo

echo "== zaxon relay filer: a tagged note gets a pointer issue, never the transcript (crt#154) =="
python3 -m unittest discover -s "$DIR" -p "test_zaxon_relay_filer.py" -v 2>&1 | tail -15 || fail=1
echo

echo "== zaxon relay server: fetch_inbox / ask_zach / send_zach =="
python3 -m unittest discover -s "$DIR" -p "test_zaxon_relay_server.py" -v 2>&1 | tail -25 || fail=1
echo

# Manifest check (2026-07-25). Every test file in this directory must be named
# above, and every name above must exist. Both directions had really drifted:
#
#   - test_audio_doctor.sh and test_mic_footer.sh were NAMED but absent, left
#   [rest: vault:crt/header-archaeology-20260817.md]
echo "== senechal guard hook (machine-config changes owe a note) =="
bash "$DIR/test_senechal_guard.sh" || fail=1
echo

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

echo "== live console state untouched (~/.crt) =="
# A console running on this same box writes ~/.crt for real reasons, so the
# comparison below cannot attribute anything and must not claim to. That is a
# SKIP, never a pass -- and it names the PID it saw, because `pgrep -f` matches
# any command line that merely MENTIONS the script (a grep, an editor, the
# shell that launched this), and a skip nobody can audit is the silent-pass
# class this whole check exists to catch. CRT_TEST_SKIP_LIVE_STATE_GUARD=1 is
# the explicit way to say "yes, a console is up, I know".
live_console_pid="$(pgrep -f '[c]rt-stt-solo\.py' 2>/dev/null | head -1)"
if [ "${CRT_TEST_SKIP_LIVE_STATE_GUARD:-0}" = "1" ]; then
  echo "SKIPPED - CRT_TEST_SKIP_LIVE_STATE_GUARD=1 (not a pass; nothing was checked)"
elif [ -n "$live_console_pid" ]; then
  echo "SKIPPED - pid $live_console_pid looks like a running console, so changes"
  echo "          under $CRT_LIVE_STATE_DIR cannot be attributed to the suite."
  echo "          Check that pid is real: ps -p $live_console_pid -o args="
elif [ "$(snapshot_live_state)" = "$LIVE_STATE_BEFORE" ]; then
  echo "ok - no test wrote into $CRT_LIVE_STATE_DIR"
else
  echo "FAIL - the suite wrote into the LIVE console state dir:"
  diff <(printf '%s\n' "$LIVE_STATE_BEFORE") <(snapshot_live_state) \
    | grep '^[<>]' | sed 's/^/    /'
  echo "    A test is using a real ~/.crt default instead of a tmp path."
  echo "    Pin the env var above (see this script's header), don't delete this check."
  fail=1
fi
echo

if [ "$fail" -eq 0 ]; then
  echo "ALL GREEN"
else
  echo "SOMETHING FAILED"
fi
exit "$fail"
