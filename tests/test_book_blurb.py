#!/usr/bin/env python3
import importlib.util
import io
import os
import sys
import tempfile
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(BIN_DIR, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bg = _load("crt_book_game_for_blurb_test", "crt-book-game.py")
bb = _load("crt_book_blurb", "crt-book-blurb.py")

SAMPLE = {
    "title": "The Left Hand of Darkness",
    "author_names": ["Ursula K. Le Guin"],
    "publish_date": "1969",
    "subjects": ["Science fiction"],
    "first_sentence": {"value": "The King was pregnant."},
}


class TestBlurbLine(unittest.TestCase):
    def test_joins_title_and_quote(self):
        self.assertEqual(bb.blurb_line("Dune", "fear is the mind-killer"),
                          "Dune -- fear is the mind-killer")

    def test_no_quote_falls_back_to_title_only(self):
        self.assertEqual(bb.blurb_line("Dune", ""), "Dune")
        self.assertEqual(bb.blurb_line("Dune", None), "Dune")

    def test_caps_to_line_width(self):
        line = bb.blurb_line("A" * 50, "quote")
        self.assertLessEqual(len(line), bb.LINE_WIDTH)
        self.assertTrue(line.endswith("..."))


class TestLookupBlurb(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.conn = bg.get_db(self.tmp.name)

    def tearDown(self):
        self.conn.close()
        os.unlink(self.tmp.name)

    def test_live_lookup_uses_first_sentence_quote(self):
        line = bb.lookup_blurb(
            "9780441478125", self.conn,
            fetcher=lambda url: SAMPLE,
            quote_fetcher=lambda url: {"query": {"search": []}})
        self.assertIn("The Left Hand of Darkness", line)
        self.assertIn("The King", line)

    def test_no_quote_anywhere_falls_back_to_static_pool(self):
        sample = dict(SAMPLE, title="Dune")
        del sample["first_sentence"]
        line = bb.lookup_blurb(
            "9780441478125", self.conn,
            fetcher=lambda url: sample,
            quote_fetcher=lambda url: {"query": {"search": []}})
        self.assertTrue(any(q[:10] in line for q in bg.FALLBACK_QUOTES))

    def test_reuses_cached_row_without_reregistering(self):
        book = bg.fetch_book_metadata("9780441478125", fetcher=lambda url: SAMPLE)
        bg.register_book(self.conn, book, questions=[{"text": "q", "options": ["a", "b"]}],
                          quote="a cached quote")
        line = bb.lookup_blurb("9780441478125", self.conn, fetcher=lambda url: 1 / 0)
        self.assertIn("a cached", line)
        row = bg.get_book(self.conn, "9780441478125")
        self.assertIn("q", row["questions_json"])

    def test_unresolvable_isbn_raises(self):
        def fetcher(url):
            raise ValueError("404")
        with self.assertRaises(ValueError):
            bb.lookup_blurb("0000000000", self.conn, fetcher=fetcher)


class TestSafeBlurb(unittest.TestCase):
    def test_swallows_lookup_failure_into_one_line(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        conn = bg.get_db(tmp.name)
        try:
            real = bb.bg.fetch_book_metadata
            bb.bg.fetch_book_metadata = lambda isbn, fetcher=None: (_ for _ in ()).throw(ValueError("boom"))
            try:
                line = bb.safe_blurb("0000000000", conn)
            finally:
                bb.bg.fetch_book_metadata = real
            self.assertIn("couldn't find that book", line)
            self.assertIn("0000000000", line)
        finally:
            conn.close()
            os.unlink(tmp.name)


class TestMain(unittest.TestCase):
    def test_argv_isbns_print_one_line_each_and_skip_non_isbn(self):
        db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        db.close()
        real_get_db = bb.bg.get_db
        bb.bg.get_db = lambda *a, **k: real_get_db(db.name)
        real_fetch = bb.bg.fetch_book_metadata
        bb.bg.fetch_book_metadata = lambda isbn, fetcher=None: dict(SAMPLE, **{"isbn": isbn, "authors": ["Ursula K. Le Guin"], "year": 1969, "raw": SAMPLE})
        buf = io.StringIO()
        real_stdout = sys.stdout
        sys.stdout = buf
        try:
            bb.main(["not-an-isbn", "9780441478125"])
        finally:
            sys.stdout = real_stdout
            bb.bg.get_db = real_get_db
            bb.bg.fetch_book_metadata = real_fetch
            os.unlink(db.name)
        out = buf.getvalue().strip().splitlines()
        self.assertEqual(len(out), 1)
        self.assertIn("The Left Hand of Darkness", out[0])


if __name__ == "__main__":
    unittest.main()
