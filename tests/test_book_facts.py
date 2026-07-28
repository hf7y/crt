#!/usr/bin/env python3
# Tests for the trivia-fact enrichment pipeline (2026-07-28, Zach-
# directed): bin/crt-book-game.py's fetch_wikipedia_extract/
# extract_fact_candidates/build_facts_batch_prompt/
# parse_facts_batch_response, plus bin/crt-book-facts-batch.py's two
# stages. No network -- fetchers/posters are injected, same pattern as
# every other AI/scrape call in this project.
import importlib.util
import json
import os
import tempfile
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")

_bg_spec = importlib.util.spec_from_file_location("crt_book_game_facts", os.path.join(BIN_DIR, "crt-book-game.py"))
bg = importlib.util.module_from_spec(_bg_spec)
_bg_spec.loader.exec_module(bg)

_fb_spec = importlib.util.spec_from_file_location("crt_book_facts_batch", os.path.join(BIN_DIR, "crt-book-facts-batch.py"))
fb = importlib.util.module_from_spec(_fb_spec)
_fb_spec.loader.exec_module(fb)


class TestFetchWikipediaExtract(unittest.TestCase):
    def test_happy_path_returns_extract(self):
        fetcher = lambda url: {"extract": "A real extract sentence here."}
        self.assertEqual(bg.fetch_wikipedia_extract("Moby-Dick", fetcher=fetcher),
                         "A real extract sentence here.")

    def test_missing_extract_key_returns_none(self):
        fetcher = lambda url: {"type": "disambiguation"}
        self.assertIsNone(bg.fetch_wikipedia_extract("Ambiguous Title", fetcher=fetcher))

    def test_empty_extract_returns_none(self):
        fetcher = lambda url: {"extract": "   "}
        self.assertIsNone(bg.fetch_wikipedia_extract("Blank", fetcher=fetcher))

    def test_network_error_returns_none_not_raises(self):
        def fetcher(url):
            raise OSError("no route to host")
        self.assertIsNone(bg.fetch_wikipedia_extract("Anything", fetcher=fetcher))

    def test_url_encodes_title(self):
        seen = {}
        def fetcher(url):
            seen["url"] = url
            return {"extract": "x is a long enough sentence to count."}
        bg.fetch_wikipedia_extract("A Title: With Punctuation & Spaces", fetcher=fetcher)
        self.assertNotIn(" ", seen["url"])
        self.assertNotIn(":", seen["url"].split("summary/")[-1])


class TestExtractFactCandidates(unittest.TestCase):
    def test_splits_into_sentences(self):
        text = "First real fact sentence here. Second real fact sentence here."
        candidates = bg.extract_fact_candidates(text)
        self.assertEqual(len(candidates), 2)

    def test_drops_short_fragments(self):
        text = "Ok. This one is long enough to actually count as a fact."
        candidates = bg.extract_fact_candidates(text)
        self.assertEqual(len(candidates), 1)
        self.assertNotIn("Ok.", candidates)

    def test_empty_input_returns_empty_list(self):
        self.assertEqual(bg.extract_fact_candidates(""), [])
        self.assertEqual(bg.extract_fact_candidates(None), [])

    def test_caps_at_max_candidates(self):
        sentence = "This is a perfectly good sentence of sufficient length. "
        text = sentence * 20
        candidates = bg.extract_fact_candidates(text)
        self.assertLessEqual(len(candidates), bg.MAX_FACT_CANDIDATES)


class TestBuildFactsBatchPrompt(unittest.TestCase):
    def test_includes_every_book_by_isbn(self):
        books = [
            {"isbn": "111", "title": "A", "authors": ["X"], "year": 2000, "facts_raw": ["s1"]},
            {"isbn": "222", "title": "B", "authors": ["Y"], "year": 2010, "facts_raw": []},
        ]
        payload = bg.build_facts_batch_prompt(books)
        isbns = [b["isbn"] for b in payload["books"]]
        self.assertEqual(isbns, ["111", "222"])

    def test_asks_for_exactly_three_facts(self):
        payload = bg.build_facts_batch_prompt([{"isbn": "1", "title": "T"}])
        self.assertIn("exactly 3", payload["instructions"])

    def test_missing_facts_raw_defaults_to_empty_list(self):
        payload = bg.build_facts_batch_prompt([{"isbn": "1", "title": "T"}])
        self.assertEqual(payload["books"][0]["candidate_sentences"], [])


class TestParseFactsBatchResponse(unittest.TestCase):
    def test_happy_path(self):
        response = {"111": ["fact one", "fact two", "fact three"]}
        self.assertEqual(bg.parse_facts_batch_response(response, "111"),
                         ["fact one", "fact two", "fact three"])

    def test_missing_isbn_returns_empty_list(self):
        self.assertEqual(bg.parse_facts_batch_response({}, "999"), [])

    def test_caps_at_three(self):
        response = {"1": ["a", "b", "c", "d", "e"]}
        self.assertEqual(bg.parse_facts_batch_response(response, "1"), ["a", "b", "c"])

    def test_drops_non_string_entries(self):
        response = {"1": ["a real fact", 42, None, {"nested": "dict"}, "another fact"]}
        self.assertEqual(bg.parse_facts_batch_response(response, "1"),
                         ["a real fact", "another fact"])

    def test_non_list_value_returns_empty(self):
        self.assertEqual(bg.parse_facts_batch_response({"1": "not a list"}, "1"), [])

    def test_malformed_response_shape_does_not_raise(self):
        self.assertEqual(bg.parse_facts_batch_response(None, "1"), [])
        self.assertEqual(bg.parse_facts_batch_response("not even a dict", "1"), [])


class _FactsBatchDBTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "books.db")
        self.conn = bg.get_db(self.db_path)

    def _register(self, isbn, title, authors=None, year=None):
        self.conn.execute(
            "INSERT INTO books (isbn, title, authors, year, subjects, raw_json, "
            "questions_json, question_source, first_scanned, last_scanned) "
            "VALUES (?, ?, ?, ?, '[]', '{}', '[]', 'template', 'now', 'now')",
            (isbn, title, json.dumps(authors or ["Unknown"]), year),
        )
        self.conn.commit()


class TestRunScrapeStage(_FactsBatchDBTestCase):
    def test_scrapes_every_book_missing_facts_raw(self):
        self._register("111", "Moby-Dick")
        self._register("222", "War and Peace")
        fetcher = lambda url: {"extract": "A sufficiently long real fact sentence about the book."}
        n = fb.run_scrape_stage(self.conn, fetcher=fetcher, log=lambda *a: None)
        self.assertEqual(n, 2)
        rows = self.conn.execute("SELECT facts_raw FROM books ORDER BY isbn").fetchall()
        self.assertTrue(all(r[0] is not None for r in rows))
        self.assertIn("sufficiently long", json.loads(rows[0][0])[0])

    def test_already_scraped_book_is_skipped(self):
        self._register("111", "Moby-Dick")
        self.conn.execute("UPDATE books SET facts_raw = ? WHERE isbn = '111'", (json.dumps(["cached"]),))
        self.conn.commit()
        called = []
        fetcher = lambda url: called.append(url) or {"extract": "should not be called"}
        n = fb.run_scrape_stage(self.conn, fetcher=fetcher, log=lambda *a: None)
        self.assertEqual(n, 0)
        self.assertEqual(called, [])

    def test_failed_lookup_still_caches_an_empty_list_not_none(self):
        self._register("111", "Nonexistent Book Title")
        fetcher = lambda url: (_ for _ in ()).throw(OSError("404"))
        fb.run_scrape_stage(self.conn, fetcher=fetcher, log=lambda *a: None)
        row = self.conn.execute("SELECT facts_raw FROM books WHERE isbn='111'").fetchone()
        self.assertIsNotNone(row[0])
        self.assertEqual(json.loads(row[0]), [])


class TestRunDistillStage(_FactsBatchDBTestCase):
    def test_no_key_configured_is_loud_no_op(self):
        self._register("111", "Moby-Dick")
        self.conn.execute("UPDATE books SET facts_raw = ? WHERE isbn = '111'", (json.dumps(["s"]),))
        self.conn.commit()
        logged = []
        n = fb.run_distill_stage(self.conn, api_key=None, log=logged.append)
        self.assertEqual(n, 0)
        self.assertTrue(any("NO GEMINI KEY" in line for line in logged))
        row = self.conn.execute("SELECT facts_json FROM books WHERE isbn='111'").fetchone()
        self.assertIsNone(row[0])

    def test_distills_facts_with_injected_key_and_poster(self):
        self._register("111", "Moby-Dick")
        self.conn.execute("UPDATE books SET facts_raw = ? WHERE isbn = '111'", (json.dumps(["s"]),))
        self.conn.commit()

        def fake_poster(url, body):
            payload = json.dumps({
                "candidates": [{"content": {"parts": [{"text": json.dumps(
                    {"111": ["fact one", "fact two", "fact three"]}
                )}]}}]
            })
            return payload.encode("utf-8")

        n = fb.run_distill_stage(self.conn, api_key="fake-key", poster=fake_poster, log=lambda *a: None)
        self.assertEqual(n, 1)
        row = self.conn.execute("SELECT facts_json FROM books WHERE isbn='111'").fetchone()
        self.assertEqual(json.loads(row[0]), ["fact one", "fact two", "fact three"])

    def test_already_distilled_book_is_skipped(self):
        self._register("111", "Moby-Dick")
        self.conn.execute(
            "UPDATE books SET facts_raw = ?, facts_json = ? WHERE isbn = '111'",
            (json.dumps(["s"]), json.dumps(["cached fact"])),
        )
        self.conn.commit()
        n = fb.run_distill_stage(self.conn, api_key="fake-key", poster=lambda *a: (_ for _ in ()).throw(AssertionError("should not be called")), log=lambda *a: None)
        self.assertEqual(n, 0)

    def test_book_still_missing_facts_raw_is_not_included(self):
        self._register("111", "Not Yet Scraped")
        n = fb.run_distill_stage(self.conn, api_key="fake-key", log=lambda *a: None)
        self.assertEqual(n, 0)

    def test_batches_respect_batch_size(self):
        for i in range(3):
            self._register(str(i), f"Book {i}")
            self.conn.execute("UPDATE books SET facts_raw = ? WHERE isbn = ?", (json.dumps(["s"]), str(i)))
        self.conn.commit()

        calls = []

        def fake_poster(url, body):
            req = json.loads(body)
            books_in_call = json.loads(req["contents"][0]["parts"][0]["text"].split("\n\n", 1)[1])
            calls.append(len(books_in_call))
            result = {b["isbn"]: ["f1", "f2", "f3"] for b in books_in_call}
            payload = json.dumps({"candidates": [{"content": {"parts": [{"text": json.dumps(result)}]}}]})
            return payload.encode("utf-8")

        old = fb.BATCH_SIZE
        fb.BATCH_SIZE = 2
        try:
            n = fb.run_distill_stage(self.conn, api_key="fake-key", poster=fake_poster, log=lambda *a: None)
        finally:
            fb.BATCH_SIZE = old
        self.assertEqual(n, 3)
        self.assertEqual(calls, [2, 1])


if __name__ == "__main__":
    unittest.main()


_bc_spec = importlib.util.spec_from_file_location("crt_book_console_for_facts", os.path.join(BIN_DIR, "crt-book-console.py"))
bc = importlib.util.module_from_spec(_bc_spec)
_bc_spec.loader.exec_module(bc)


class TestFactLinesForHint(unittest.TestCase):
    def test_no_facts_json_returns_none(self):
        self.assertIsNone(bc.fact_lines_for_hint({"facts_json": None}, 40))

    def test_empty_facts_list_returns_none(self):
        self.assertIsNone(bc.fact_lines_for_hint({"facts_json": json.dumps([])}, 40))

    def test_missing_key_returns_none_not_raises(self):
        self.assertIsNone(bc.fact_lines_for_hint({}, 40))

    def test_malformed_json_returns_none_not_raises(self):
        self.assertIsNone(bc.fact_lines_for_hint({"facts_json": "not json"}, 40))

    def test_returns_wrapped_centered_lines_for_first_fact(self):
        row = {"facts_json": json.dumps(["A short real fact.", "second", "third"])}
        lines = bc.fact_lines_for_hint(row, 40)
        self.assertIsNotNone(lines)
        self.assertTrue(any("A short real fact." in l for l in lines))
        self.assertNotIn("second", " ".join(lines))

    def test_caps_at_fact_hint_max_rows(self):
        row = {"facts_json": json.dumps(["word " * 200])}
        lines = bc.fact_lines_for_hint(row, 40)
        self.assertLessEqual(len(lines), bc.FACT_HINT_MAX_ROWS)


class TestRenderScanResultUsesFacts(unittest.TestCase):
    def test_waiting_hint_shows_fact_when_available(self):
        row = {"title": "Dune", "questions_json": json.dumps(
            [{"text": "Fiction or nonfiction?", "options": ["fiction", "nonfiction"], "correct": "fiction"}]),
            "facts_json": json.dumps(["Dune won the Hugo Award in 1966."])}
        lines = bc.render_scan_result(row, 40, 15, show_waiting_hint=True)
        self.assertTrue(any("Hugo Award" in l for l in lines))

    def test_waiting_hint_falls_back_to_cat_art_without_facts(self):
        row = {"title": "Dune", "questions_json": json.dumps(
            [{"text": "Fiction or nonfiction?", "options": ["fiction", "nonfiction"], "correct": "fiction"}]),
            "facts_json": None}
        lines_with = bc.render_scan_result(row, 40, 15, show_waiting_hint=True)
        lines_without = bc.render_scan_result(row, 40, 15, show_waiting_hint=False)
        self.assertNotEqual(lines_with, lines_without)


class TestFactsBatchAlreadyRunning(unittest.TestCase):
    def test_true_when_pgrep_finds_a_pid(self):
        class Result:
            stdout = "12345\n"
        self.assertTrue(bc.facts_batch_already_running(runner=lambda cmd: Result()))

    def test_false_when_pgrep_finds_nothing(self):
        class Result:
            stdout = ""
        self.assertFalse(bc.facts_batch_already_running(runner=lambda cmd: Result()))


class TestMaybeTriggerFactsBatch(_FactsBatchDBTestCase):
    def test_does_not_fire_below_threshold(self):
        self._register("1", "A")
        self._register("2", "B")
        spawned = []
        fired = bc.maybe_trigger_facts_batch(
            self.conn, spawner=lambda cmd: spawned.append(cmd),
            runner=lambda cmd: type("R", (), {"stdout": ""})())
        self.assertFalse(fired)
        self.assertEqual(spawned, [])

    def test_fires_once_at_or_above_threshold(self):
        for i in range(bc.FACTS_BATCH_TRIGGER):
            self._register(str(i), f"Book {i}")
        spawned = []
        fired = bc.maybe_trigger_facts_batch(
            self.conn, spawner=lambda cmd: spawned.append(cmd),
            runner=lambda cmd: type("R", (), {"stdout": ""})())
        self.assertTrue(fired)
        self.assertEqual(len(spawned), 1)
        self.assertIn("crt-book-facts-batch.py", spawned[0][-1])

    def test_does_not_fire_if_already_running(self):
        for i in range(bc.FACTS_BATCH_TRIGGER):
            self._register(str(i), f"Book {i}")
        spawned = []
        fired = bc.maybe_trigger_facts_batch(
            self.conn, spawner=lambda cmd: spawned.append(cmd),
            runner=lambda cmd: type("R", (), {"stdout": "99999\n"})())
        self.assertFalse(fired)
        self.assertEqual(spawned, [])

    def test_books_already_distilled_do_not_count_toward_threshold(self):
        for i in range(bc.FACTS_BATCH_TRIGGER):
            self._register(str(i), f"Book {i}")
            self.conn.execute("UPDATE books SET facts_json = ? WHERE isbn = ?",
                              (json.dumps(["done"]), str(i)))
        self.conn.commit()
        spawned = []
        fired = bc.maybe_trigger_facts_batch(
            self.conn, spawner=lambda cmd: spawned.append(cmd),
            runner=lambda cmd: type("R", (), {"stdout": ""})())
        self.assertFalse(fired)
