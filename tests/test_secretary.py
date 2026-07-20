#!/usr/bin/env python3
# Offline tests for bin/crt-secretary.py's playbook registry (SUPERVISOR.md)
# -- exercises matching + the deterministic-local-state handlers (status,
# run_tests, what_time) without tmux/Claude/TTS/printer hardware, by
# monkeypatching the side-effecting functions (speak/print_full/sh).
import importlib.util
import os
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
