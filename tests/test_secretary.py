#!/usr/bin/env python3
# Offline tests for bin/crt-secretary.py's playbook registry (SUPERVISOR.md)
# -- exercises matching + the deterministic-local-state handlers (status,
# run_tests, what_time) without tmux/Claude/TTS/printer hardware, by
# monkeypatching the side-effecting functions (speak/print_full/sh).
import importlib.util
import os
import tempfile
import unittest

# Pin the live-console state defaults into tmp BEFORE any bin/ module is
# imported and reads them at module scope (2026-07-25). This file was one of
# five appending to the REAL ~/.crt -- the capture-duck control channel a
# running crt-stt-solo.py reads live, and the state crt-window-switcher.py
# reads to decide whether a brain is behind the screen. tests/run_tests.sh
# pins these for the whole suite; this covers running this file on its own.
_state = tempfile.mkdtemp(prefix="crt-test-state-")
os.environ.setdefault("CRT_CTL_FILE", os.path.join(_state, "ctl"))
os.environ.setdefault("CRT_CLAUDE_ACTIVE_STATE",
                      os.path.join(_state, "claude-window-active.state"))
os.environ.setdefault("CRT_THOUGHT_LOG", os.path.join(_state, "thoughts.log"))
os.environ.setdefault("CRT_STT_GATE_LOG", os.path.join(_state, "thoughts.log"))

BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")
REPO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def load_secretary():
    spec = importlib.util.spec_from_file_location(
        "crt_secretary", os.path.join(BIN_DIR, "crt-secretary.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestPlaybookMatching(unittest.TestCase):
    def setUp(self):
        self.sec = load_secretary()

    def test_status_matches_variants(self):
        for phrase in ("what's up", "any reports for me", "anything new?",
                       "give me a status"):
            name, _ = self.sec.find_playbook(phrase)
            self.assertEqual(name, "status", phrase)

    def test_run_tests_matches(self):
        name, _ = self.sec.find_playbook("can you run the tests")
        self.assertEqual(name, "run_tests")

    def test_morning_report_matches(self):
        name, _ = self.sec.find_playbook("give me the morning report")
        self.assertEqual(name, "morning_report")

    def test_calibrate_matches(self):
        name, _ = self.sec.find_playbook("calibrate the display")
        self.assertEqual(name, "calibrate")

    def test_what_time_matches(self):
        name, _ = self.sec.find_playbook("what time is it")
        self.assertEqual(name, "what_time")

    def test_novel_request_matches_nothing(self):
        name, action = self.sec.find_playbook("refactor the audio pipeline")
        self.assertIsNone(name)
        self.assertIsNone(action)

    def test_first_match_wins_no_double_fire(self):
        # A phrase that could plausibly brush two playbooks should still
        # resolve to exactly one -- ordering in PLAYBOOKS is the tiebreak.
        name, _ = self.sec.find_playbook("status: run the tests please")
        self.assertIn(name, ("status", "run_tests"))


class TestStatusPlaybook(unittest.TestCase):
    def setUp(self):
        self.sec = load_secretary()
        self.tmpdir = tempfile.mkdtemp()
        self.sec.REPORTS_DIR = self.tmpdir
        self.sec.QUESTIONS = os.path.join(self.tmpdir, "QUESTIONS.md")
        self.spoken = []
        self.printed = []
        self.sec.speak = lambda text, device="handset": self.spoken.append(text)
        self.sec.print_full = lambda text: self.printed.append(text)

    def test_quiet_when_nothing_new(self):
        self.sec.handle_status("what's up")
        self.assertIn("quiet", self.spoken[0].lower())
        self.assertEqual(self.printed, [])

    def test_speaks_count_and_prints_when_items_exist(self):
        with open(os.path.join(self.tmpdir, "LATEST.md"), "w") as f:
            f.write("- **09:00 (note):** something happened\n")
        self.sec.handle_status("what's up")
        self.assertIn("waiting", self.spoken[0].lower())
        self.assertEqual(len(self.printed), 1)
        self.assertIn("something happened", self.printed[0])


class TestRunTestsPlaybook(unittest.TestCase):
    def setUp(self):
        self.sec = load_secretary()
        self.spoken = []
        self.sec.speak = lambda text, device="handset": self.spoken.append(text)
        self.sec.print_full = lambda text: None

    def test_reports_missing_suite(self):
        self.sec.TEST_SUITE = "/nonexistent/run_tests.sh"
        self.sec.handle_run_tests("run the tests")
        self.assertIn("don't see", self.spoken[0].lower())

    def test_runs_real_suite_and_reports_green(self):
        # Uses this repo's own real test suite -- if THIS test is running,
        # the suite it's part of had better still be green.
        # Skip when we're ALREADY inside run_tests.sh (it exports this
        # marker): otherwise this shells back out to run_tests.sh and
        # recurses without bound. Standalone runs (no marker) still verify.
        if os.environ.get("CRT_TEST_SUITE_RUNNING"):
            self.skipTest("running inside run_tests.sh; would recurse")
        self.sec.TEST_SUITE = os.path.join(REPO_DIR, "tests", "run_tests.sh")
        self.sec.handle_run_tests("run the tests")
        self.assertIn("green", self.spoken[0].lower())


class _FakeResult:
    def __init__(self, stdout):
        self.stdout = stdout
        self.returncode = 0


class TestMorningReportPlaybook(unittest.TestCase):
    def setUp(self):
        self.sec = load_secretary()
        self.spoken = []
        self.printed = []
        self.sec.speak = lambda text, device="handset": self.spoken.append(text)
        self.sec.print_full = lambda text: self.printed.append(text)

    def test_missing_presenter_speaks_and_does_not_crash(self):
        self.sec.MORNING_REPORT_BIN = "/nonexistent/presenter.py"
        self.sec.handle_morning_report("morning report")
        self.assertIn("don't have", self.spoken[0].lower())
        self.assertEqual(self.printed, [])

    def test_no_sections_speaks_nothing_new(self):
        self.sec.MORNING_REPORT_BIN = __file__  # any existing path works
        self.sec.sh = lambda cmd, **kw: _FakeResult("")
        self.sec.handle_morning_report("morning report")
        self.assertIn("nothing", self.spoken[0].lower())

    def test_sections_present_speaks_count_and_prints_full(self):
        self.sec.MORNING_REPORT_BIN = __file__
        calls = []

        def fake_sh(cmd, **kw):
            calls.append(cmd)
            if cmd[-1] == "screen":
                return _FakeResult("chezz: all green\nwtul: rip speed shipped\n")
            return _FakeResult("full report body here")

        self.sec.sh = fake_sh
        self.sec.handle_morning_report("morning report")
        self.assertIn("2 project", self.spoken[0])
        self.assertEqual(self.printed, ["full report body here"])
        self.assertEqual(len(calls), 2)


class TestBookGameStatsPlaybook(unittest.TestCase):
    def setUp(self):
        self.sec = load_secretary()
        self.spoken = []
        self.printed = []
        self.sec.speak = lambda text, device="handset": self.spoken.append(text)
        self.sec.print_full = lambda text: self.printed.append(text)

    def test_missing_tool_speaks_and_does_not_crash(self):
        self.sec.BOOK_GAME_STATS_BIN = "/nonexistent/stats.py"
        self.sec.handle_book_game_stats("book game stats")
        self.assertIn("don't have", self.spoken[0].lower())
        self.assertEqual(self.printed, [])

    def test_speaks_screen_output_and_prints_full(self):
        self.sec.BOOK_GAME_STATS_BIN = __file__
        calls = []

        def fake_sh(cmd, **kw):
            calls.append(cmd)
            if cmd[-1] == "screen":
                return _FakeResult("Book Game: 3 book(s) scanned\n1 answer(s) graded, STT accuracy 100%\n")
            return _FakeResult("full report body here")

        self.sec.sh = fake_sh
        self.sec.handle_book_game_stats("how's the book game")
        self.assertIn("3 book(s) scanned", self.spoken[0])
        self.assertEqual(self.printed, ["full report body here"])
        self.assertEqual(len(calls), 2)

    def test_matches_trigger_variants(self):
        for phrase in ("book game stats", "how's the book game", "trivia stats",
                       "how's the training data"):
            name, _ = self.sec.find_playbook(phrase)
            self.assertEqual(name, "book_game_stats", phrase)


class TestBookCatalogPlaybook(unittest.TestCase):
    def setUp(self):
        self.sec = load_secretary()
        self.spoken = []
        self.printed = []
        self.sec.speak = lambda text, device="handset": self.spoken.append(text)
        self.sec.print_full = lambda text: self.printed.append(text)

    def test_missing_tool_speaks_and_does_not_crash(self):
        self.sec.BOOK_CATALOG_BIN = "/nonexistent/catalog.py"
        self.sec.handle_book_catalog("my library")
        self.assertIn("don't have", self.spoken[0].lower())
        self.assertEqual(self.printed, [])

    def test_speaks_screen_output_and_prints_full(self):
        self.sec.BOOK_CATALOG_BIN = __file__
        calls = []

        def fake_sh(cmd, **kw):
            calls.append(cmd)
            if cmd[-1] == "screen":
                return _FakeResult("2 book(s) in your library.\nLatest: Dune\n")
            return _FakeResult("full catalog body here")

        self.sec.sh = fake_sh
        self.sec.handle_book_catalog("my library")
        self.assertIn("Latest: Dune", self.spoken[0])
        self.assertEqual(self.printed, ["full catalog body here"])
        self.assertEqual(len(calls), 2)

    def test_matches_trigger_variants(self):
        for phrase in ("my library", "book catalog", "list my books",
                       "what books have i scanned"):
            name, _ = self.sec.find_playbook(phrase)
            self.assertEqual(name, "book_catalog", phrase)


class TestCalibratePlaybook(unittest.TestCase):
    def setUp(self):
        self.sec = load_secretary()
        self.spoken = []
        self.printed_stdout = []
        self.sec.speak = lambda text, device="handset": self.spoken.append(text)

    def test_missing_tool_speaks_and_does_not_crash(self):
        self.sec.CALIBRATE_BIN = "/nonexistent/calibrate.py"
        self.sec.handle_calibrate("calibrate the display")
        self.assertIn("don't have", self.spoken[0].lower())

    def test_empty_pattern_speaks_failure(self):
        self.sec.CALIBRATE_BIN = __file__
        self.sec.sh = lambda cmd, **kw: _FakeResult("")
        self.sec.handle_calibrate("calibrate the display")
        self.assertIn("couldn't render", self.spoken[0].lower())

    def test_real_pattern_writes_to_stdout_and_speaks_ack(self):
        self.sec.CALIBRATE_BIN = __file__
        self.sec.sh = lambda cmd, **kw: _FakeResult("AAAA\nBBBB\n")
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.sec.handle_calibrate("calibrate the display")
        self.assertIn("AAAA", buf.getvalue())
        self.assertEqual(len(self.spoken), 1)


class TestWhatTimePlaybook(unittest.TestCase):
    def test_speaks_something_time_shaped(self):
        sec = load_secretary()
        spoken = []
        sec.speak = lambda text, device="handset": spoken.append(text)
        sec.handle_what_time("what time is it")
        self.assertEqual(len(spoken), 1)
        self.assertTrue(spoken[0].startswith("It's") or spoken[0][0].isdigit())


class TestFallthroughLogging(unittest.TestCase):
    def setUp(self):
        self.sec = load_secretary()
        self.tmpdir = tempfile.mkdtemp()
        self.sec.FALLTHROUGH_LOG = os.path.join(self.tmpdir, "fallthrough.log")
        # Stub out the whole Claude-routing path -- this is about whether
        # the log write happens, not about tmux/Claude behavior.
        self.sec.capture_pane = lambda: ""
        self.sec.send_to_claude = lambda text: True
        self.sec.wait_for_claude_reply = lambda before, on_partial=None: ("", "ok")
        self.sec.route_claude_reply = lambda reply: None

    def test_matched_playbook_does_not_log(self):
        self.sec.speak = lambda text, device="handset": None
        self.sec.handle("what time is it")
        self.assertFalse(os.path.exists(self.sec.FALLTHROUGH_LOG))

    def test_unmatched_request_gets_logged(self):
        self.sec.handle("refactor the audio pipeline please")
        self.assertTrue(os.path.exists(self.sec.FALLTHROUGH_LOG))
        with open(self.sec.FALLTHROUGH_LOG) as f:
            content = f.read()
        self.assertIn("refactor the audio pipeline please", content)

    def test_multiple_fallthroughs_append_not_overwrite(self):
        self.sec.handle("first novel request")
        self.sec.handle("second novel request")
        with open(self.sec.FALLTHROUGH_LOG) as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
        self.assertEqual(len(lines), 2)

    def test_broken_log_path_does_not_crash_routing(self):
        # A directory that can't be created (parent is actually a file)
        # must not prevent the real Claude-routing fallback from running.
        blocker = os.path.join(self.tmpdir, "not_a_dir")
        open(blocker, "w").close()
        self.sec.FALLTHROUGH_LOG = os.path.join(blocker, "fallthrough.log")
        called = []
        self.sec.send_to_claude = lambda text: (called.append(text), True)[1]
        self.sec.handle("this should still reach claude")
        self.assertEqual(called, ["this should still reach claude"])


class TestAnswersMatch(unittest.TestCase):
    def setUp(self):
        self.sec = load_secretary()

    def test_substring_match_either_direction(self):
        self.assertTrue(self.sec._answers_match("3 15 pm", "the time right now is 3 15 pm exactly"))
        self.assertTrue(self.sec._answers_match("all green tests passed", "all green"))

    def test_no_match(self):
        self.assertFalse(self.sec._answers_match("all green tests passed", "it's 3:15 PM"))

    def test_empty_inputs_never_match(self):
        self.assertFalse(self.sec._answers_match("", "anything"))
        self.assertFalse(self.sec._answers_match("anything", ""))
        self.assertFalse(self.sec._answers_match(None, "anything"))


class TestMediaPlaybook(unittest.TestCase):
    def setUp(self):
        self.sec = load_secretary()
        self.spoken = []
        self.sec.speak = lambda text, device="handset": self.spoken.append(text)
        self.sec.MEDIA_BACKEND = self.sec.media_player.FakeBackend()

    def test_matches_play_command(self):
        name, _ = self.sec.find_playbook("play some jazz")
        self.assertEqual(name, "media")

    def test_matches_control_words(self):
        # Bare "next" deliberately excluded -- see crt-media-player.py's
        # header: it's claimed by crt-stt-solo.py's own CONTROL dict for
        # single-word utterances, "skip" is the reachable equivalent.
        for phrase in ("pause", "resume", "skip", "stop"):
            name, _ = self.sec.find_playbook(phrase)
            self.assertEqual(name, "media", phrase)

    def test_play_dispatches_to_backend_and_speaks(self):
        self.sec.handle_media("play some jazz")
        self.assertEqual(self.sec.MEDIA_BACKEND.calls, [("play", "some jazz")])
        self.assertIn("jazz", self.spoken[0])

    def test_non_media_text_does_not_match(self):
        name, _ = self.sec.find_playbook("what time is it")
        self.assertNotEqual(name, "media")


class TestReturnToBookGamePlaybook(unittest.TestCase):
    def setUp(self):
        self.sec = load_secretary()
        self.switched = []
        self.sec.switch_tmux_window = lambda name: self.switched.append(name)

    def test_matches_trigger_variants(self):
        for phrase in ("book game", "back to the game", "switch to book game"):
            name, _ = self.sec.find_playbook(phrase)
            self.assertEqual(name, "return_to_book_game", phrase)

    def test_does_not_shadow_book_game_stats(self):
        # "book game" is a substring of "book game stats" -- the more
        # specific playbook must still win.
        name, _ = self.sec.find_playbook("book game stats")
        self.assertEqual(name, "book_game_stats")

    def test_does_not_shadow_book_catalog(self):
        name, _ = self.sec.find_playbook("my library")
        self.assertEqual(name, "book_catalog")

    def test_switches_to_book_window(self):
        self.sec.handle_return_to_book_game("book game")
        self.assertEqual(self.switched, [self.sec.BOOK_WINDOW])


class TestClaudeWindowSwitch(unittest.TestCase):
    def setUp(self):
        self.sec = load_secretary()
        self.sec.FALLTHROUGH_LOG = os.path.join(tempfile.mkdtemp(), "fallthrough.log")
        self.sec.capture_pane = lambda: ""
        self.sec.send_to_claude = lambda text: True
        self.sec.wait_for_claude_reply = lambda before, on_partial=None: ("", "ok")
        self.sec.route_claude_reply = lambda reply: None

    def test_fallthrough_switches_to_claude_view_window(self):
        switched = []
        self.sec.switch_tmux_window = lambda name: switched.append(name)
        self.sec.handle("refactor the audio pipeline please")
        self.assertEqual(switched, [self.sec.CLAUDE_VIEW_WINDOW])

    def test_fallthrough_touches_claude_active_state(self):
        touched = []
        self.sec.touch_claude_active = lambda: touched.append(True)
        self.sec.handle("refactor the audio pipeline please")
        self.assertEqual(len(touched), 2)  # once before, once after the reply

    def test_matched_playbook_never_switches_window(self):
        switched = []
        self.sec.switch_tmux_window = lambda name: switched.append(name)
        self.sec.speak = lambda text, device="handset": None
        self.sec.handle("what time is it")
        self.assertEqual(switched, [])

    def test_touch_claude_active_writes_a_timestamp(self):
        with tempfile.TemporaryDirectory() as d:
            self.sec.CLAUDE_ACTIVE_STATE = os.path.join(d, "state")
            self.sec.touch_claude_active()
            with open(self.sec.CLAUDE_ACTIVE_STATE) as f:
                float(f.read())  # must parse as a real timestamp

    def test_touch_claude_active_broken_path_does_not_raise(self):
        blocker = os.path.join(tempfile.mkdtemp(), "not_a_dir")
        open(blocker, "w").close()
        self.sec.CLAUDE_ACTIVE_STATE = os.path.join(blocker, "state")
        self.sec.touch_claude_active()  # must not raise


class TestSpeculativeFiller(unittest.TestCase):
    def setUp(self):
        self.sec = load_secretary()
        self.sec.FALLTHROUGH_LOG = os.path.join(tempfile.mkdtemp(), "fallthrough.log")
        self.sec.capture_pane = lambda: ""
        self.sec.send_to_claude = lambda text: True
        self.sec.wait_for_claude_reply = lambda before, on_partial=None: ("", "ok")
        self.sec.route_claude_reply = lambda reply: None

    def test_disabled_by_default_no_filler_call(self):
        self.assertFalse(self.sec.SPECULATE_ENABLED)
        calls = []
        self.sec.show_filler_line = lambda: calls.append(True)
        self.sec.handle("refactor the audio pipeline please")
        self.assertEqual(calls, [])

    def test_enabled_calls_filler_before_claude(self):
        self.sec.SPECULATE_ENABLED = True
        order = []
        self.sec.show_filler_line = lambda: order.append("filler")
        self.sec.send_to_claude = lambda text: (order.append("claude"), True)[1]
        self.sec.handle("refactor the audio pipeline please")
        self.assertEqual(order, ["filler", "claude"])

    def test_matched_playbook_never_shows_filler(self):
        self.sec.SPECULATE_ENABLED = True
        self.sec.speak = lambda text, device="handset": None
        calls = []
        self.sec.show_filler_line = lambda: calls.append(True)
        self.sec.handle("what time is it")
        self.assertEqual(calls, [])

    def test_show_filler_line_calls_crt_think_with_a_pool_line(self):
        calls = []
        self.sec.sh = lambda cmd, **kw: calls.append(cmd)
        self.sec.show_filler_line()
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0][0].endswith("crt-think.sh"))
        self.assertIn(calls[0][1], self.sec.speculate.FILLER_LINES)

    def test_show_filler_line_never_raises_on_broken_sh(self):
        def boom(cmd, **kw):
            raise OSError("no such file")
        self.sec.sh = boom
        self.sec.show_filler_line()  # must not raise


class TestConfidenceRouting(unittest.TestCase):
    def setUp(self):
        self.sec = load_secretary()
        self.tmpdir = tempfile.mkdtemp()
        self.sec.stt_confidence.STATE_PATH = os.path.join(self.tmpdir, "stt-confidence.json")

    def test_disabled_by_default_runs_action_only(self):
        self.assertFalse(self.sec.CONFIDENCE_ENABLED)
        calls = []
        action = lambda text: (calls.append(text), "answer")[1]
        result = self.sec.confidence_route("what time is it", action)
        self.assertEqual(result, "answer")
        self.assertEqual(calls, ["what time is it"])
        # No background confirmation should have touched state at all.
        self.assertEqual(self.sec.stt_confidence.load_state(), {})

    def test_enabled_spawns_background_thread(self):
        self.sec.CONFIDENCE_ENABLED = True
        self.sec.stt_confidence.should_call_claude = lambda text, state, rng: False
        action = lambda text: "the local answer"
        # should_call_claude=False means the thread returns immediately
        # without touching tmux -- safe to run for real in a test.
        result = self.sec.confidence_route("what time is it", action)
        self.assertEqual(result, "the local answer")

    def test_confirm_in_background_records_hit_on_match(self):
        self.sec.stt_confidence.should_call_claude = lambda text, state, rng: True
        self.sec.capture_pane = lambda: "before"
        self.sec.send_to_claude = lambda text: True
        self.sec.wait_for_claude_reply = lambda before, on_partial=None: ("It's 3:15 PM exactly", "ok")
        self.sec._confirm_in_background("what time is it", "It's 3:15 PM.")
        state = self.sec.stt_confidence.load_state()
        key = self.sec.stt_confidence.normalize_key("what time is it")
        self.assertEqual(state[key]["confirmed_hits"], 1)
        self.assertEqual(state[key]["claude_hits"], 1)

    def test_confirm_in_background_no_hit_on_mismatch(self):
        self.sec.stt_confidence.should_call_claude = lambda text, state, rng: True
        self.sec.capture_pane = lambda: "before"
        self.sec.send_to_claude = lambda text: True
        self.sec.wait_for_claude_reply = lambda before, on_partial=None: ("completely unrelated reply", "ok")
        self.sec._confirm_in_background("what time is it", "It's 3:15 PM.")
        state = self.sec.stt_confidence.load_state()
        key = self.sec.stt_confidence.normalize_key("what time is it")
        self.assertEqual(state[key]["confirmed_hits"], 0)
        self.assertEqual(state[key]["claude_hits"], 1)


class TestUndeliveredUtterance(unittest.TestCase):
    """A dropped reverse tunnel used to be indistinguishable from a Claude
    that simply had nothing to say (2026-07-25): send_to_claude() discarded
    _bridge_request()'s result, which is "" on any socket failure, so
    handle() fired the "thinking" earcon and sat through the full idle wait
    before saying "I sent that to Claude but didn't catch a reply -- check
    the screen" -- wrong twice over (nothing was sent; that screen is blank
    because the brain isn't there). These tests pin the observable
    behaviour, not the implementation.
    """

    def setUp(self):
        self.sec = load_secretary()
        self.tmp = tempfile.mkdtemp()
        self.sec.FALLTHROUGH_LOG = os.path.join(self.tmp, "fallthrough.log")
        self.sec.BRAIN_LOG = os.path.join(self.tmp, "brain-unreachable.log")
        self.spoken, self.earcons, self.thought = [], [], []
        self.sec.speak = lambda text, device="handset": self.spoken.append(text)
        self.sec.play_earcon = lambda name: self.earcons.append(name)
        self.sec.switch_tmux_window = lambda name: None
        self.sec.touch_claude_active = lambda: None
        self.sec.capture_pane = lambda: ""
        self.sec.sh = lambda cmd, **kw: self.thought.append(cmd) or _ok()

    # -- send_to_claude's return contract, remote path -------------------

    def _remote(self, response):
        self.sec.CLAUDE_REMOTE_PORT = 18993
        self.sec._bridge_request = lambda command, port, timeout=None: response

    def test_remote_ok_is_delivered(self):
        self._remote("OK")
        self.assertTrue(self.sec.send_to_claude("hello"))

    def test_remote_silence_is_not_delivered(self):
        """"" is what _bridge_request returns for connection-refused, i.e.
        the tunnel is down -- the exact case this was blind to."""
        self._remote("")
        self.assertFalse(self.sec.send_to_claude("hello"))

    def test_remote_err_is_not_delivered(self):
        self._remote("ERR can't find session: potato-claude")
        self.assertFalse(self.sec.send_to_claude("hello"))

    def test_undelivered_utterance_is_logged_with_a_reason(self):
        self._remote("ERR can't find session: potato-claude")
        self.sec.send_to_claude("what did I leave in the oven")
        with open(self.sec.BRAIN_LOG) as f:
            line = f.read()
        self.assertIn("what did I leave in the oven", line)
        self.assertIn("can't find session", line)

    def test_bridge_silence_logs_the_port_it_could_not_reach(self):
        self._remote("")
        self.sec.send_to_claude("hello")
        with open(self.sec.BRAIN_LOG) as f:
            self.assertIn("18993", f.read())

    # -- send_to_claude's return contract, local tmux path ---------------

    def test_local_send_keys_failure_is_not_delivered(self):
        self.sec.CLAUDE_REMOTE_PORT = None
        self.sec.sh = lambda cmd, **kw: _fail("can't find session: crt")
        self.assertFalse(self.sec.send_to_claude("hello"))

    def test_local_enter_failure_is_not_delivered(self):
        """The literal text can land and the Enter still fail, which leaves
        a half-typed prompt in Claude's input and no reply."""
        self.sec.CLAUDE_REMOTE_PORT = None
        calls = []

        def fake_sh(cmd, **kw):
            calls.append(cmd)
            return _ok() if len(calls) == 1 else _fail("session died")

        self.sec.sh = fake_sh
        self.assertFalse(self.sec.send_to_claude("hello"))

    def test_local_success_is_delivered(self):
        self.sec.CLAUDE_REMOTE_PORT = None
        self.sec.sh = lambda cmd, **kw: _ok()
        self.assertTrue(self.sec.send_to_claude("hello"))

    # -- what handle() does about it -------------------------------------

    def test_failed_send_never_promises_a_reply(self):
        self.sec.send_to_claude = lambda text: False
        self.sec.wait_for_claude_reply = lambda before, on_partial=None: \
            self.fail("must not wait on a send that never landed")
        self.sec.handle("refactor the audio pipeline please")
        self.assertNotIn("thinking", self.earcons)

    def test_failed_send_says_so_out_loud(self):
        self.sec.send_to_claude = lambda text: False
        self.sec.wait_for_claude_reply = lambda before, on_partial=None: ("", "ok")
        self.sec.handle("refactor the audio pipeline please")
        self.assertEqual(self.spoken, [self.sec.BRAIN_UNREACHABLE_LINE])

    def test_failed_send_does_not_claim_it_sent_anything(self):
        """Distinguishable BY EAR from route_claude_reply()'s reached-Claude
        line, which is the whole point of having a second line at all."""
        self.sec.send_to_claude = lambda text: False
        self.sec.wait_for_claude_reply = lambda before, on_partial=None: ("", "ok")
        self.sec.handle("refactor the audio pipeline please")
        self.assertNotIn("I sent that to Claude", " ".join(self.spoken))

    def test_failed_send_puts_something_on_the_screen_it_switched_to(self):
        self.sec.send_to_claude = lambda text: False
        self.sec.handle("refactor the audio pipeline please")
        joined = " ".join(" ".join(c) for c in self.thought)
        self.assertIn("crt-think.sh", joined)

    def test_successful_send_still_fires_the_thinking_earcon(self):
        self.sec.send_to_claude = lambda text: True
        self.sec.wait_for_claude_reply = lambda before, on_partial=None: ("an answer", "ok")
        self.sec.route_claude_reply = lambda reply: None
        self.sec.handle("refactor the audio pipeline please")
        self.assertIn("thinking", self.earcons)

    # -- and what it does NOT do to the confidence model ------------------

    def test_failed_send_records_no_claude_call(self):
        """Recording one would book an unconfirmed miss against this
        utterance every time the tunnel was down -- teaching the model that
        the local playbook disagrees with a Claude that never answered."""
        self.sec.stt_confidence.should_call_claude = lambda text, state, rng: True
        recorded = []
        self.sec.stt_confidence.record_claude_call = \
            lambda text, state: recorded.append(text)
        self.sec.send_to_claude = lambda text: False
        self.sec.wait_for_claude_reply = lambda before, on_partial=None: \
            self.fail("must not wait on a send that never landed")
        self.sec._confirm_in_background("what time is it", "It's 3:15 PM.")
        self.assertEqual(recorded, [])


class TestUnobservedReply(unittest.TestCase):
    """A send that lands and an answer nobody could read (2026-07-25).

    These inject at the real failure boundary -- what the bridge socket
    returns -- rather than stubbing capture_pane(), because the defect WAS
    capture_pane() collapsing failure into "". Stubbing it would have
    reproduced neither bug.

    Both cases are measured against the pre-fix code in the report; the
    control case below is what pins that the fix didn't just make everything
    say "unobserved".
    """

    PANE = "\n".join("scrollback line %d: an old exchange about audio" % i
                     for i in range(200))

    def setUp(self):
        self.sec = load_secretary()
        self.tmp = tempfile.mkdtemp()
        self.sec.BRAIN_LOG = os.path.join(self.tmp, "brain-unreachable.log")
        self.sec.FALLTHROUGH_LOG = os.path.join(self.tmp, "fallthrough.log")
        self.sec.CLAUDE_REMOTE_PORT = 18993     # the live deployment shape
        self.sec.CLAUDE_POLL = 0.01
        self.sec.CLAUDE_IDLE_SECS = 0.02
        self.sec.CLAUDE_MAX_WAIT = 2
        self.spoken, self.printed, self.earcons = [], [], []
        self.sec.speak = lambda text, device="handset": self.spoken.append(text)
        self.sec.print_full = lambda text: self.printed.append(text)
        self.sec.play_earcon = lambda name: self.earcons.append(name)
        self.sec.switch_tmux_window = lambda name: None
        self.sec.touch_claude_active = lambda: None
        self.sec.sh = lambda cmd, **kw: _ok()

    def _bridge(self, capture_responses):
        """capture_responses: what CAPTURE returns, in order; the last value
        repeats. "" is _bridge_request's real value for a dropped tunnel or a
        bridge whose tmux target is gone. SEND always succeeds here -- the
        point is what happens AFTER the utterance has landed."""
        seq = list(capture_responses)

        def request(command, port, timeout=None):
            if command.startswith("SEND"):
                return "OK"
            return seq.pop(0) if len(seq) > 1 else seq[0]

        self.sec._bridge_request = request

    def test_no_baseline_does_not_read_the_scrollback_aloud(self):
        """The baseline capture failing used to make every line on the pane
        "new": 160 characters of an old exchange spoken into the earpiece."""
        self._bridge(["", self.PANE])
        self.sec.handle("what did I leave in the oven")
        self.assertNotIn("scrollback line", " ".join(self.spoken))

    def test_no_baseline_does_not_print_the_scrollback(self):
        """...and the rest of it handed to print_full(), which is a Phomemo
        M02 thermal receipt printer (bin/crt-print.sh)."""
        self._bridge(["", self.PANE])
        self.sec.handle("what did I leave in the oven")
        self.assertEqual(self.printed, [])

    def test_no_baseline_says_it_lost_the_answer(self):
        self._bridge(["", self.PANE])
        self.sec.handle("what did I leave in the oven")
        self.assertEqual(self.spoken, [self.sec.REPLY_UNOBSERVED_LINE])

    def test_drop_after_send_does_not_blame_claude_for_being_quiet(self):
        """The other half of FOCUS.md's named top-priority failure: the
        tunnel dropping once the utterance is already gone. It used to
        produce the same "didn't catch a reply -- check the screen" sentence
        that send_to_claude()'s own fix was about."""
        self._bridge([self.PANE, ""])
        self.sec.handle("what did I leave in the oven")
        self.assertNotIn("didn't catch a reply", " ".join(self.spoken))
        self.assertEqual(self.spoken, [self.sec.REPLY_UNOBSERVED_LINE])

    def test_drop_after_send_leaves_evidence(self):
        self._bridge([self.PANE, ""])
        self.sec.handle("what did I leave in the oven")
        with open(self.sec.BRAIN_LOG) as f:
            logged = f.read()
        self.assertIn("what did I leave in the oven", logged)
        self.assertIn("unreadable", logged)
        # ...and it must not say the opposite of what happened. The utterance
        # WAS delivered; only the answer went missing.
        self.assertIn("DELIVERED, REPLY UNOBSERVED", logged)
        self.assertNotIn("NOT DELIVERED", logged)

    def test_unobserved_reply_is_audible_not_silent(self):
        self._bridge([self.PANE, ""])
        self.sec.handle("what did I leave in the oven")
        self.assertIn("oops", self.earcons)

    def test_a_transient_miss_does_not_end_the_wait(self):
        """One unreadable capture is a hiccup on the tunnel, not a verdict --
        the real answer still arrives on the next poll."""
        answer = self.PANE + "\nthere is a casserole in the oven"
        self._bridge([self.PANE, "", answer])
        self.sec.handle("what did I leave in the oven")
        self.assertEqual(self.spoken, ["there is a casserole in the oven"])

    def test_a_working_exchange_is_unchanged(self):
        """The control. Byte-identical to the pre-fix behaviour, which is
        what makes the two failure assertions above mean anything."""
        answer = self.PANE + "\nthere is a casserole in the oven"
        self._bridge([self.PANE, answer])
        self.sec.handle("what did I leave in the oven")
        self.assertEqual(self.spoken, ["there is a casserole in the oven"])
        self.assertEqual(self.earcons, ["thinking"])

    # -- capture_pane's own contract: None (unreadable) vs "" (read, empty) --

    def test_remote_empty_capture_is_unreadable_not_empty(self):
        self.sec._bridge_request = lambda command, port, timeout=None: ""
        self.assertIsNone(self.sec.capture_pane())

    def test_remote_real_capture_comes_back_as_text(self):
        self.sec._bridge_request = lambda command, port, timeout=None: "hello"
        self.assertEqual(self.sec.capture_pane(), "hello")

    def test_local_capture_failure_is_unreadable(self):
        self.sec.CLAUDE_REMOTE_PORT = None
        self.sec.sh = lambda cmd, **kw: _fail("can't find pane")
        self.assertIsNone(self.sec.capture_pane())

    def test_local_empty_pane_is_not_a_failure(self):
        """A local tmux capture that succeeds with no output is a genuinely
        empty pane, and its diff is meaningful. Only the remote path treats
        empty as unreadable, and only because "" is all a dead bridge gives."""
        self.sec.CLAUDE_REMOTE_PORT = None
        self.sec.sh = lambda cmd, **kw: _Completed(0)
        self.assertEqual(self.sec.capture_pane(), "")

    def test_unobserved_reply_records_no_confidence_hit(self):
        """The same defect one step later than send_to_claude()'s: an answer
        nobody could read is not an answer that disagreed."""
        self.sec.stt_confidence.should_call_claude = lambda text, state, rng: True
        recorded = []
        self.sec.stt_confidence.record_claude_call = \
            lambda text, state: recorded.append(text)
        self._bridge([self.PANE, ""])
        self.sec._confirm_in_background("what time is it", "It's 3:15 PM.")
        self.assertEqual(recorded, [])


class _Completed(object):
    def __init__(self, returncode, stderr=""):
        self.returncode, self.stderr, self.stdout = returncode, stderr, ""


def _ok():
    return _Completed(0)


def _fail(stderr):
    return _Completed(1, stderr)


if __name__ == "__main__":
    unittest.main()
