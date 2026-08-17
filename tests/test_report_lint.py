#!/usr/bin/env python3
"""bin/crt-report-lint.py -- one heading text per report file.

The regression this guards is not hypothetical: three consecutive cycles on
2026-07-25 opened with an inline reply from Zach pointing at a bug fixed two
cycles earlier, because the day's report carried every earlier cycle verbatim
and the reply's "Section: ## New issues found" anchor had four candidates.
See the script's header.
"""
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import unittest

BIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")
LINT = os.path.join(BIN, "crt-report-lint.py")


def load():
    spec = importlib.util.spec_from_file_location("crt_report_lint", LINT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestHeadingExtraction(unittest.TestCase):
    def setUp(self):
        self.m = load()

    def test_finds_headings_at_every_level(self):
        text = "# one\n\n## two\n\n###### six\n"
        self.assertEqual([h[2] for h in self.m.headings(text)], ["one", "two", "six"])

    def test_ignores_shell_comments_in_fenced_blocks(self):
        """A report quoting a command must not have its comments counted as
        headings -- these reports quote shell constantly."""
        text = "# real\n\n```\n# not a heading\n# also not\n```\n\n## also real\n"
        self.assertEqual([h[2] for h in self.m.headings(text)], ["real", "also real"])

    def test_tilde_fences_close_too(self):
        text = "~~~\n# hidden\n~~~\n# visible\n"
        self.assertEqual([h[2] for h in self.m.headings(text)], ["visible"])

    def test_hash_without_space_is_not_a_heading(self):
        self.assertEqual(self.m.headings("#nospace\n"), [])

    def test_reports_line_numbers(self):
        text = "intro\n\n## second line three\n"
        self.assertEqual(self.m.headings(text)[0][0], 3)


class TestDuplicateDetection(unittest.TestCase):
    def setUp(self):
        self.m = load()

    def test_clean_report_has_no_duplicates(self):
        text = "# report\n\n## one\n\n## two\n"
        self.assertEqual(self.m.duplicates(text), {})

    def test_the_real_nested_cycle_shape_is_caught(self):
        """The exact structure that broke the reply channel: a day's report
        with the previous cycle appended verbatim underneath it."""
        cycle = "# crt nightly batch\n\n## New issues found\n\n- a thing\n"
        text = cycle + "\n---\n\n# Earlier cycles\n\n" + cycle
        dups = self.m.duplicates(text)
        self.assertIn("crt nightly batch", dups)
        self.assertIn("new issues found", dups)

    def test_level_does_not_rescue_a_repeat(self):
        """'## Foo' and '### Foo' are equally ambiguous to an anchor that
        quotes only the text."""
        self.assertIn("foo", self.m.duplicates("## Foo\n\n### Foo\n"))

    def test_case_and_spacing_do_not_rescue_a_repeat(self):
        self.assertIn("new issues found",
                      self.m.duplicates("## New issues found\n\n##  new   ISSUES found\n"))

    def test_distinct_headings_that_merely_share_words_are_fine(self):
        text = "## New issues found\n\n## New issues found (earlier cycle)\n"
        self.assertEqual(self.m.duplicates(text), {})


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _write(self, name, text):
        path = os.path.join(self.tmp, name)
        with open(path, "w") as f:
            f.write(text)
        return path

    def _run(self, *args):
        return subprocess.run([sys.executable, LINT] + list(args),
                              capture_output=True, text=True)

    def test_clean_file_exits_zero(self):
        path = self._write("ok.md", "# r\n\n## one\n\n## two\n")
        r = self._run(path)
        self.assertEqual(r.returncode, 0)
        self.assertIn("every heading occurs once", r.stdout)

    def test_duplicate_exits_one_and_names_both_lines(self):
        path = self._write("bad.md", "## New issues found\n\nx\n\n## New issues found\n")
        r = self._run(path)
        self.assertEqual(r.returncode, 1)
        self.assertIn("line 1", r.stderr)
        self.assertIn("line 5", r.stderr)

    def test_failure_says_what_to_do_about_it(self):
        """The next instance of this tier reads only the failure text."""
        path = self._write("bad.md", "## a\n\n## a\n")
        self.assertIn("own file", self._run(path).stderr)

    def test_one_bad_file_among_good_ones_still_fails(self):
        good = self._write("good.md", "## fine\n")
        bad = self._write("bad.md", "## a\n\n## a\n")
        self.assertEqual(self._run(good, bad).returncode, 1)

    def test_missing_file_is_loud_not_clean(self):
        """'never looked' must not share an exit code with 'nothing found'."""
        r = self._run(os.path.join(self.tmp, "nope.md"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("nope.md", r.stderr)

    def test_no_arguments_is_a_usage_error_not_a_pass(self):
        r = self._run()
        self.assertEqual(r.returncode, 2)
        self.assertIn("usage", r.stderr)


# TestCommittedReports was here. It scanned .reports-fallback/ -- 24 committed
# copies of nightly-batch reports, all dated 2026-07-23 or 2026-07-25 -- and
# asserted the directory was non-empty. Those copies are deleted; the lint is
# NOT. It still runs on live reports in ~/reports/crt/, and every unit test
# above still pins its behaviour on synthetic fixtures.
#
# The enforcement that mattered is unchanged: a cycle that nests an earlier
# report inside the current one still fails, because the lint still checks
# that. What is gone is a three-week-old archive being re-linted on every run
# as a proxy for it.


if __name__ == "__main__":
    unittest.main()
