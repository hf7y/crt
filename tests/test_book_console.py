#!/usr/bin/env python3
# Tests for bin/crt-book-console.py's pure functions (parsing, rendering,
# scan-handling) -- see BOOK-GAME-STYLE.md. No tmux, no live terminal;
# the tail-follow loop / draw() itself is exercised only by inspection,
# same acceptance bar as every other crt-console.sh window.
import importlib.util
import json
import os
import queue
import tempfile
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")

_bg_spec = importlib.util.spec_from_file_location("crt_book_game", os.path.join(BIN_DIR, "crt-book-game.py"))
bg = importlib.util.module_from_spec(_bg_spec)
_bg_spec.loader.exec_module(bg)

_bc_spec = importlib.util.spec_from_file_location("crt_book_console", os.path.join(BIN_DIR, "crt-book-console.py"))
bc = importlib.util.module_from_spec(_bc_spec)
_bc_spec.loader.exec_module(bc)


class TestParseScannerLogLine(unittest.TestCase):
    def test_parses_valid_line(self):
        self.assertEqual(bc.parse_scanner_log_line("2026-07-21T12:00:00\t9780141439518\n"), "9780141439518")

    def test_rejects_no_tab(self):
        self.assertIsNone(bc.parse_scanner_log_line("no tab here"))

    def test_rejects_non_isbn_text(self):
        self.assertIsNone(bc.parse_scanner_log_line("2026-07-21T12:00:00\tnot an isbn"))


class TestParseStdinScanLine(unittest.TestCase):
    def test_parses_bare_isbn_line(self):
        self.assertEqual(bc.parse_stdin_scan_line("9780141439518\n"), "9780141439518")

    def test_rejects_non_isbn_text(self):
        self.assertIsNone(bc.parse_stdin_scan_line("hello there\n"))

    def test_rejects_empty_line(self):
        self.assertIsNone(bc.parse_stdin_scan_line("\n"))

    def test_strips_whitespace(self):
        self.assertEqual(bc.parse_stdin_scan_line("  9780141439518  \n"), "9780141439518")


class _StubRng:
    """Deterministic stand-in for random.Random -- fixes .random()'s
    return so tests can force render_idle_screen's caption-branch choice
    instead of depending on luck-of-the-seed."""
    def __init__(self, value):
        self.value = value

    def random(self):
        return self.value

    def choice(self, seq):
        return seq[0]


class TestRenderIdleScreen(unittest.TestCase):
    def test_dimensions(self):
        lines = bc.render_idle_screen(3, 40, 15, rng=_StubRng(0.9))
        self.assertEqual(len(lines), 15)

    def test_mentions_book_count_when_count_branch_wins(self):
        lines = bc.render_idle_screen(5, 40, 15, rng=_StubRng(0.9))  # >=0.5 -> count branch
        self.assertTrue(any("5 book(s)" in l for l in lines))

    def test_shows_enticement_when_entice_branch_wins(self):
        lines = bc.render_idle_screen(5, 40, 15, rng=_StubRng(0.1))  # <0.5 -> entice branch
        prefix = bg.ENTICE_LINES[0][:20]  # full line may exceed the 40-col caption width
        self.assertTrue(any(prefix in l for l in lines))
        self.assertFalse(any("book(s) registered" in l for l in lines))

    def test_colored_with_title_register(self):
        lines = bc.render_idle_screen(0, 40, 15, rng=_StubRng(0.9))
        self.assertTrue(all(l.startswith(bg.COLOR_TITLE) for l in lines))


class TestRenderScanResult(unittest.TestCase):
    def test_renders_question_from_row(self):
        row = {"title": "Dune", "questions_json": json.dumps(
            [{"text": "Fiction or nonfiction?", "options": ["fiction", "nonfiction"], "correct": "fiction"}])}
        lines = bc.render_scan_result(row, 40, 15)
        self.assertTrue(any("Dune" in l for l in lines))
        self.assertTrue(any("fiction" in l for l in lines))

    def test_handles_missing_questions(self):
        row = {"title": "Mystery", "questions_json": json.dumps([])}
        lines = bc.render_scan_result(row, 40, 15)
        self.assertTrue(any("no question on file" in l for l in lines))


class TestHandleScan(unittest.TestCase):
    def test_fresh_scan_registers_book(self):
        with tempfile.TemporaryDirectory() as d:
            conn = bg.get_db(os.path.join(d, "books.db"))
            fetcher = lambda url: {"title": "Test Book", "author_names": ["A B"], "publish_date": "1999"}
            quote_fetcher = lambda url: {"query": {"search": []}}  # no Wikiquote page -- scrape_quote returns None
            row = bc.handle_scan(conn, "123", fetcher=fetcher, quote_fetcher=quote_fetcher)
            self.assertEqual(row["title"], "Test Book")

    def test_fresh_scan_caches_scraped_quote(self):
        with tempfile.TemporaryDirectory() as d:
            conn = bg.get_db(os.path.join(d, "books.db"))
            fetcher = lambda url: {"title": "Test Book"}
            calls = {"search": {"query": {"search": [{"title": "Test Book"}]}},
                      "revisions": {"query": {"pages": [{"revisions": [{"slots": {"main": {
                          "content": "* A quote long enough to pass the length filter here.\n** Ch. 1"}}}]}]}}}
            def quote_fetcher(url):
                return calls["search"] if "list=search" in url else calls["revisions"]
            row = bc.handle_scan(conn, "123", fetcher=fetcher, quote_fetcher=quote_fetcher)
            self.assertIn("A quote long enough", row["quote"])

    def test_rescan_reuses_cached_row_no_refetch_no_rescrape(self):
        with tempfile.TemporaryDirectory() as d:
            conn = bg.get_db(os.path.join(d, "books.db"))
            fetcher = lambda url: {"title": "Test Book"}
            quote_fetcher = lambda url: {"query": {"search": []}}
            row1 = bc.handle_scan(conn, "123", fetcher=fetcher, quote_fetcher=quote_fetcher)
            boom = lambda url: (_ for _ in ()).throw(AssertionError("should not refetch"))
            row2 = bc.handle_scan(conn, "123", fetcher=boom, quote_fetcher=boom)
            self.assertEqual(row1["title"], row2["title"])

    def test_unknown_isbn_raises_scan_lookup_failed_not_raw_error(self):
        # Confirmed live: Open Library 404s on an unrecognized ISBN --
        # this must surface as ScanLookupFailed, not urllib's own
        # exception type, so main()'s except clause can catch exactly
        # this without swallowing unrelated bugs.
        with tempfile.TemporaryDirectory() as d:
            conn = bg.get_db(os.path.join(d, "books.db"))

            def not_found(url):
                raise OSError("HTTP Error 404: Not Found")

            with self.assertRaises(bc.ScanLookupFailed):
                bc.handle_scan(conn, "0000000000", fetcher=not_found)

    def test_network_error_also_raises_scan_lookup_failed(self):
        with tempfile.TemporaryDirectory() as d:
            conn = bg.get_db(os.path.join(d, "books.db"))

            def timeout(url):
                raise TimeoutError("timed out")

            with self.assertRaises(bc.ScanLookupFailed):
                bc.handle_scan(conn, "123", fetcher=timeout)


class TestRenderScanError(unittest.TestCase):
    def test_dimensions_and_isbn_shown(self):
        lines = bc.render_scan_error("0000000000", 40, 15)
        self.assertEqual(len(lines), 15)
        self.assertTrue(any("0000000000" in l for l in lines))

    def test_colored_wrong_register(self):
        lines = bc.render_scan_error("123", 40, 15)
        self.assertTrue(any(l.startswith(bg.COLOR_WRONG) for l in lines if l.strip()))


class _FakeStdin:
    """A fake sys.stdin: an iterable that yields a fixed set of lines
    then stops (simulating EOF), or raises partway through (simulating
    a read error) -- either way, stdin_reader() must still push
    STDIN_DEAD so the failure isn't silent."""
    def __init__(self, lines, raise_after=None):
        self.lines = lines
        self.raise_after = raise_after

    def __iter__(self):
        for i, line in enumerate(self.lines):
            if self.raise_after is not None and i == self.raise_after:
                raise OSError("simulated stdin read error")
            yield line


class TestStdinReaderDeathIsSurfaced(unittest.TestCase):
    def setUp(self):
        self.orig_stdin = bc.sys.stdin

    def tearDown(self):
        bc.sys.stdin = self.orig_stdin

    def test_eof_pushes_sentinel_after_real_lines(self):
        bc.sys.stdin = _FakeStdin(["9780141439518\n"])
        q = queue.Queue()
        bc.stdin_reader(q)  # runs to completion synchronously (fake stdin ends)
        items = []
        while True:
            try:
                items.append(q.get_nowait())
            except queue.Empty:
                break
        self.assertEqual(items[0], "9780141439518\n")
        self.assertIs(items[-1], bc.STDIN_DEAD)

    def test_read_error_still_pushes_sentinel(self):
        bc.sys.stdin = _FakeStdin(["one\n", "two\n"], raise_after=1)
        q = queue.Queue()
        bc.stdin_reader(q)
        items = []
        while True:
            try:
                items.append(q.get_nowait())
            except queue.Empty:
                break
        self.assertIs(items[-1], bc.STDIN_DEAD)


class TestWarnStdinDead(unittest.TestCase):
    def test_writes_to_thought_log(self):
        with tempfile.TemporaryDirectory() as d:
            bc.THOUGHT_LOG = os.path.join(d, "thoughts.log")
            bc.warn_stdin_dead()
            with open(bc.THOUGHT_LOG) as f:
                content = f.read()
            self.assertIn("stdin scan reader died", content)
            self.assertTrue(content.startswith(bg.COLOR_WRONG))

    def test_broken_path_does_not_raise(self):
        blocker = os.path.join(tempfile.mkdtemp(), "not_a_dir")
        open(blocker, "w").close()
        bc.THOUGHT_LOG = os.path.join(blocker, "thoughts.log")
        bc.warn_stdin_dead()  # must not raise


if __name__ == "__main__":
    unittest.main()
