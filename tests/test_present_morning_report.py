#!/usr/bin/env python3
# Offline tests for bin/crt-present-morning-report.py's pure parsing/
# formatting logic, against a synthetic sample matching the real shape of
# Project Archive/scheduler/bin/morning-report.sh's stdout -- no scheduler
# invocation, no VM, no Claude.
import importlib.util
import os
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")
spec = importlib.util.spec_from_file_location(
    "crt_present", os.path.join(BIN_DIR, "crt-present-morning-report.py"))
present = importlib.util.module_from_spec(spec)
spec.loader.exec_module(present)

SAMPLE = """\
════════════════════════════════════════
  chezz
════════════════════════════════════════
# Chezz nightly — 2026-07-18

First run tracked under `~/reports/chezz/`.

## Shipped
- Board-corruption fix, the big one.

════════════════════════════════════════
  DEPLOY PENDING
════════════════════════════════════════
-- vkv-inventory --
  live build is BEHIND origin — a deploy is pending.
  run:  clasp push

════════════════════════════════════════
  Open questions
════════════════════════════════════════
-- chezz --
- **2026-07-18 (nightly): Stalemate — reset the floor or die?**
  reporters are split.
"""


class TestParseSections(unittest.TestCase):
    def setUp(self):
        self.sections = present.parse_sections(SAMPLE)

    def test_finds_all_three_sections_in_order(self):
        names = [s["name"] for s in self.sections]
        self.assertEqual(names, ["chezz", "DEPLOY PENDING", "Open questions"])

    def test_headline_strips_markdown_hash_and_uses_first_content_line(self):
        chezz = self.sections[0]
        self.assertEqual(chezz["headline"], "Chezz nightly — 2026-07-18")

    def test_headline_falls_back_to_first_nonempty_line_without_hash(self):
        deploy = self.sections[1]
        self.assertEqual(deploy["headline"], "-- vkv-inventory --")

    def test_body_contains_full_section_text(self):
        chezz = self.sections[0]
        self.assertIn("Board-corruption fix", chezz["body"])
        # must NOT bleed into the next section
        self.assertNotIn("DEPLOY PENDING", chezz["body"])
        self.assertNotIn("clasp push", chezz["body"])

    def test_empty_input_yields_no_sections(self):
        self.assertEqual(present.parse_sections(""), [])


class TestFormatScreenLine(unittest.TestCase):
    def test_short_line_unmodified(self):
        s = {"name": "wtul", "headline": "all green"}
        line = present.format_screen_line(s, width=40)
        self.assertEqual(line, "wtul: all green")

    def test_long_line_truncated_with_ellipsis(self):
        s = {"name": "chezz", "headline": "x" * 100}
        line = present.format_screen_line(s, width=40)
        self.assertLessEqual(len(line), 40)
        self.assertTrue(line.endswith("..."))

    def test_truncation_never_exceeds_requested_width(self):
        for width in (10, 20, 40, 80):
            s = {"name": "p", "headline": "y" * 200}
            line = present.format_screen_line(s, width=width)
            self.assertLessEqual(len(line), width)


class TestFetchTimeout(unittest.TestCase):
    def test_hanging_script_returns_empty_not_hang(self):
        import subprocess as sp

        def fake_run(*a, **kw):
            raise sp.TimeoutExpired(cmd="morning-report.sh", timeout=1)

        orig = present.subprocess.run
        present.subprocess.run = fake_run
        try:
            out = present.fetch_raw()
        finally:
            present.subprocess.run = orig
        self.assertEqual(out, "")


class TestMainCommands(unittest.TestCase):
    def setUp(self):
        # Bypass the real scheduler invocation entirely -- point fetch_raw
        # at the synthetic sample so main()'s command dispatch is testable
        # without any external script.
        present.fetch_raw = lambda script=None: SAMPLE

    def _run(self, argv, capsys_target):
        import io, contextlib, sys as _sys
        old_argv = _sys.argv
        _sys.argv = ["crt-present-morning-report.py"] + argv
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                present.main()
        finally:
            _sys.argv = old_argv
        return buf.getvalue()

    def test_screen_command_lists_all_sections(self):
        out = self._run(["screen"], None)
        self.assertIn("chezz:", out)
        self.assertIn("DEPLOY PENDING:", out)
        self.assertIn("Open questions:", out)

    def test_print_command_returns_only_requested_section(self):
        out = self._run(["print", "chezz"], None)
        self.assertIn("Board-corruption fix", out)
        self.assertNotIn("clasp push", out)

    def test_print_all_returns_everything(self):
        out = self._run(["print-all"], None)
        self.assertIn("Board-corruption fix", out)
        self.assertIn("clasp push", out)
        self.assertIn("Stalemate", out)


if __name__ == "__main__":
    unittest.main()
