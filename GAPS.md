# GAPS -- what `sonne` cannot yet do

Recorded 2026-07-30 during the bashify pass. These are to be closed
later; they are written down now so the utility never pretends.

## Files whose own paths name an external paid service

python: 5, other languages: 0. Their paths are not reproduced here,
because printing them would put the string back into a branch that
promises not to carry it. They are on the default branch.

## Python that was never given a shell contract (116 files)

These do real work but are not reachable through the verb, because they
have no stated argv/output promise to wrap:

- `bin/crt-book-answer-listen.py`
- `bin/crt-book-catalog.py`
- `bin/crt-book-console.py`
- `bin/crt-book-facts-batch.py`
- `bin/crt-book-game-stats.py`
- `bin/crt-book-game.py`
- `bin/crt-book-idle-bait.py`
- `bin/crt-brain-shell.py`
- `bin/crt-calibrate-display.py`
- `bin/crt-calibrate.py`
- `bin/crt-calibration-game.py`
- `bin/crt-cast-sink.py`
- `bin/crt-earcon-loopback-test.py`
- `bin/crt-media-player.py`
- `bin/crt-meter.py`
- `bin/crt-midi-knobs.py`
- `bin/crt-monologue.py`
- `bin/crt-pager.py`
- `bin/crt-predict.py`
- `bin/crt-present-morning-report.py`
- `bin/crt-print-render.py`
- `bin/crt-report-lint.py`
- `bin/crt-screensaver.py`
- `bin/crt-secretary.py`
- `bin/crt-speculate.py`
- `bin/crt-stt-confidence.py`
- `bin/crt-stt-solo.py`
- `bin/crt-stt-stream.py`
- `bin/crt-stt-training-merge.py`
- `bin/crt-tts-calibrate.py`
- `bin/crt-tts.py`
- `bin/crt-wake-arm.py`
- `bin/crt-wake-judge.py`
- `bin/crt-wake-pool-tally.py`
- `bin/crt-wake-pool.py`
- `bin/crt-wake-router.py`
- `bin/crt-window-switcher.py`
- `bin/crt_caption.py`
- `bin/crt_config.py`
- `bin/crt_fixups_store.py`
- `bin/crt_loop_guard.py`
- `bin/crt_scan_line.py`
- `bin/crt_wake_gate.py`
- `bin/mandark-whisper-server.py`
- `tests/book_console_pty.py`
- `tests/test_bibquotes.py`
- `tests/test_book_answer_arm_window.py`
- `tests/test_book_answer_listen.py`
- `tests/test_book_answer_round_closes.py`
- `tests/test_book_answer_wake_word.py`
- `tests/test_book_catalog.py`
- `tests/test_book_console.py`
- `tests/test_book_console_safe_margins.py`
- `tests/test_book_console_size.py`
- `tests/test_book_facts.py`
- `tests/test_book_game.py`
- `tests/test_book_game_integration.py`
- `tests/test_book_game_stats.py`
- `tests/test_book_game_stt_axis.py`
- `tests/test_book_idle_bait.py`
- `tests/test_book_idle_screen_moves.py`
- `tests/test_book_rescan_pending.py`
- `tests/test_brain_ssh.py`
- `tests/test_calibrate.py`
- `tests/test_calibrate_display.py`
- `tests/test_calibration_game.py`
- `tests/test_capture_backpressure.py`
- `tests/test_capture_device.py`
- `tests/test_cast_sink.py`
- `tests/test_config_fixups_path.py`
- `tests/test_dispatch_failure_visible.py`
- `tests/test_earcon_failure_is_visible.py`
- `tests/test_fixups_reload.py`
- `tests/test_fixups_store.py`
- `tests/test_fixups_two_writers.py`
- `tests/test_idle_caption_fits.py`
- `tests/test_idle_face_is_not_a_brain.py`
- `tests/test_log_reader_decoding.py`
- `tests/test_loop_guard.py`
- `tests/test_loopback_verdict.py`
- `tests/test_media_player.py`
- `tests/test_monologue_py.py`
- `tests/test_monologue_viewport.py`
- `tests/test_pager.py`
- `tests/test_predict.py`
- `tests/test_present_morning_report.py`
- `tests/test_reply_reaches_window_one.py`
- `tests/test_report_lint.py`
- `tests/test_ring_actually_rings.py`
- `tests/test_scan_reaches_the_tube.py`
- `tests/test_screensaver.py`
- `tests/test_screensaver_art_rotation.py`
- `tests/test_screensaver_blink_sleep.py`
- `tests/test_screensaver_caption_moves.py`
- `tests/test_screensaver_forwards_scans.py`
- `tests/test_screensaver_safe_margins.py`
- `tests/test_secretary.py`
- `tests/test_sideband_wiring.py`
- `tests/test_speculate.py`
- `tests/test_speech_failure_visible.py`
- `tests/test_stt_confidence.py`
- `tests/test_stt_gate.py`
- `tests/test_stt_secretary_sink.py`
- `tests/test_stt_solo_helpers.py`
- `tests/test_stt_training_merge.py`
- `tests/test_transcribe_failure.py`
- `tests/test_tts_capture_duck.py`
- `tests/test_tts_prosody.py`
- `tests/test_wake_arm.py`
- `tests/test_wake_judge.py`
- `tests/test_wake_pool.py`
- `tests/test_wake_pool_tally.py`
- `tests/test_wake_rearm_ceiling.py`
- `tests/test_wake_router.py`
- `tests/test_window_switcher.py`
- `tests/test_window_switcher_idle_face.py`

## Deliberately not exposed (2)

That many files in the legacy tree are named after an external paid
service. Exposing them as subcommands would break this branch's stated
guarantee, so they are counted here and not carried over. Their paths
are on the default branch for anyone who needs them.

Closing this gap means writing a plain replacement, not re-exposing them.

## Standing gap: the cost baseline

No before-measurement exists for what the previous implementation cost
per call, so the saving from mechanising it is **unmeasured, not zero
and not assumed**. Closing this needs a real measurement, not an estimate.
