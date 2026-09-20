import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bin"))
import crt_console_windows as m  # noqa: E402

CONSOLE_SH = os.path.join(os.path.dirname(__file__), "..", "bin", "crt-console.sh")


class TestParseWindows(unittest.TestCase):
    def setUp(self):
        with open(CONSOLE_SH) as fh:
            self.windows = m.parse_windows(fh.read())
        self.by_name = {name: cmd for name, cmd in self.windows}

    def test_every_named_window_from_the_real_console_script_is_found(self):
        for name in ("mono", "bridge", "stt", "hook", "book", "bookidle",
                     "bibquotes", "bookanswer", "windowswitch", "stttrain"):
            self.assertIn(name, self.by_name, f"crt-console.sh no longer defines window {name!r}?")

    def test_stt_window_command_names_its_backing_supervisor(self):
        self.assertIn("crt-stt-supervisor.sh", self.by_name["stt"])

    def test_line_continuation_is_joined_before_matching(self):
        with open(CONSOLE_SH) as fh:
            text = fh.read()
        self.assertIn("\\\n", text, "fixture assumption stale: no continued line left to test")


class TestAffectedWindows(unittest.TestCase):
    def setUp(self):
        self.windows = [
            ("stt", "./crt-stt-supervisor.sh; exec bash"),
            ("book", "python3 ./crt-book-console.py; exec bash"),
            ("mono", "./crt-monologue.py; exec bash"),
        ]

    def test_a_changed_backing_script_names_its_window(self):
        self.assertEqual(m.affected_windows(["bin/crt-stt-supervisor.sh"], self.windows), ["stt"])

    def test_multiple_changed_files_can_hit_multiple_windows(self):
        hit = m.affected_windows(["bin/crt-stt-supervisor.sh", "bin/crt-book-console.py"], self.windows)
        self.assertEqual(hit, ["stt", "book"])

    def test_an_unrelated_file_hits_nothing(self):
        self.assertEqual(m.affected_windows(["README.md"], self.windows), [])

    def test_empty_changed_list_hits_nothing(self):
        self.assertEqual(m.affected_windows([], self.windows), [])


if __name__ == "__main__":
    unittest.main()
