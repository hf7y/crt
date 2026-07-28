#!/usr/bin/env python3
# Tests for the trivia-fact enrichment pipeline (2026-07-28, Zach-
# directed): bin/crt-book-game.py's fetch_wikipedia_extract/
# extract_fact_candidates/build_facts_batch_prompt, plus
# bin/crt-book-facts-batch.py's two stages and bin/crt-book-console.py's
# batch trigger. No network -- fetchers/posters are injected, same
# pattern as every other AI/scrape call in this project.
#
# REDESIGNED same day, still live: the first version distilled facts_raw
# into bare fact strings shown as flavor text next to the STILL-GENERIC
# template question. Zach caught it live ("I'm still getting generic
# facts?") and redirected: "clean design is to phrase it as a question
# ... Who guest edited the 2016 edition? Answer: Junot Diaz." The
# distill stage now writes real, fact-grounded two-option questions
# DIRECTLY into questions_json (parsed by the pre-existing
# parse_claude_batch_response, already covered in test_book_game.py --
# not re-tested here), replacing the generic question outright. facts_json
# is vestigial (column kept, nothing reads/writes it) -- see
# bin/crt-book-game.py's schema-migration comment.
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

_bc_spec = importlib.util.spec_from_file_location("crt_book_console_for_facts", os.path.join(BIN_DIR, "crt-book-console.py"))
bc = importlib.util.module_from_spec(_bc_spec)
_bc_spec.loader.exec_module(bc)


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

    def test_asks_for_exactly_three_questions(self):
        payload = bg.build_facts_batch_prompt([{"isbn": "1", "title": "T"}])
        self.assertIn("exactly 3", payload["instructions"])

    def test_asks_for_questions_not_generic_ones(self):
        payload = bg.build_facts_batch_prompt([{"isbn": "1", "title": "T"}])
        self.assertIn("not generic fiction/nonfiction", payload["instructions"])

    def test_asks_for_the_existing_question_schema(self):
        # Deliberately the SAME shape parse_claude_batch_response already
        # expects (options/correct) -- this is a better-grounded filler
        # for the existing question mechanism, not a new one.
        payload = bg.build_facts_batch_prompt([{"isbn": "1", "title": "T"}])
        self.assertIn('"options"', payload["instructions"])
        self.assertIn('"correct"', payload["instructions"])

    def test_missing_facts_raw_defaults_to_empty_list(self):
        payload = bg.build_facts_batch_prompt([{"isbn": "1", "title": "T"}])
        self.assertEqual(payload["books"][0]["candidate_sentences"], [])


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


def _fake_gemini_poster(result_by_isbn):
    """A poster (see bg.call_gemini_batch) that returns `result_by_isbn`
    verbatim as the parsed batch response, wrapped in Gemini's real
    envelope shape."""
    def poster(url, body):
        payload = json.dumps({
            "candidates": [{"content": {"parts": [{"text": json.dumps(result_by_isbn)}]}}]
        })
        return payload.encode("utf-8")
    return poster


class TestRunDistillStage(_FactsBatchDBTestCase):
    def test_no_key_configured_is_loud_no_op(self):
        self._register("111", "Moby-Dick")
        self.conn.execute("UPDATE books SET facts_raw = ? WHERE isbn = '111'", (json.dumps(["s"]),))
        self.conn.commit()
        logged = []
        n = fb.run_distill_stage(self.conn, api_key=None, log=logged.append)
        self.assertEqual(n, 0)
        self.assertTrue(any("NO GEMINI KEY" in line for line in logged))
        row = self.conn.execute("SELECT questions_json, question_source FROM books WHERE isbn='111'").fetchone()
        self.assertEqual(json.loads(row[0]), [])
        self.assertEqual(row[1], "template")

    def test_writes_real_questions_into_questions_json_with_injected_key_and_poster(self):
        self._register("111", "Moby-Dick")
        self.conn.execute("UPDATE books SET facts_raw = ? WHERE isbn = '111'", (json.dumps(["s"]),))
        self.conn.commit()

        poster = _fake_gemini_poster({"111": [
            {"text": "Who narrates Moby-Dick?", "options": ["Ishmael", "Ahab"], "correct": "Ishmael"},
        ]})

        n = fb.run_distill_stage(self.conn, api_key="fake-key", poster=poster, log=lambda *a: None)
        self.assertEqual(n, 1)
        row = self.conn.execute("SELECT questions_json, question_source FROM books WHERE isbn='111'").fetchone()
        questions = json.loads(row[0])
        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0]["text"], "Who narrates Moby-Dick?")
        self.assertEqual(questions[0]["correct"], "Ishmael")
        self.assertEqual(row[1], fb.ENRICHED_SOURCE)

    def test_already_enriched_book_is_skipped(self):
        self._register("111", "Moby-Dick")
        self.conn.execute(
            "UPDATE books SET facts_raw = ?, questions_json = ?, question_source = ? WHERE isbn = '111'",
            (json.dumps(["s"]), json.dumps([{"text": "cached", "options": ["a", "b"], "correct": "a"}]),
             fb.ENRICHED_SOURCE),
        )
        self.conn.commit()

        def boom(url, body):
            raise AssertionError("should not be called")

        n = fb.run_distill_stage(self.conn, api_key="fake-key", poster=boom, log=lambda *a: None)
        self.assertEqual(n, 0)

    def test_book_still_missing_facts_raw_is_not_included(self):
        self._register("111", "Not Yet Scraped")
        n = fb.run_distill_stage(self.conn, api_key="fake-key", log=lambda *a: None)
        self.assertEqual(n, 0)

    def test_no_usable_questions_returned_leaves_book_unenriched_for_retry(self):
        self._register("111", "Moby-Dick")
        self.conn.execute("UPDATE books SET facts_raw = ? WHERE isbn = '111'", (json.dumps(["s"]),))
        self.conn.commit()
        poster = _fake_gemini_poster({})  # no entry for this ISBN at all
        n = fb.run_distill_stage(self.conn, api_key="fake-key", poster=poster, log=lambda *a: None)
        self.assertEqual(n, 0)
        row = self.conn.execute("SELECT question_source FROM books WHERE isbn='111'").fetchone()
        self.assertEqual(row[0], "template", "must not be marked enriched on a failed distill")

    def test_batches_respect_batch_size(self):
        for i in range(3):
            self._register(str(i), f"Book {i}")
            self.conn.execute("UPDATE books SET facts_raw = ? WHERE isbn = ?", (json.dumps(["s"]), str(i)))
        self.conn.commit()

        calls = []

        def poster(url, body):
            req = json.loads(body)
            books_in_call = json.loads(req["contents"][0]["parts"][0]["text"].split("\n\n", 1)[1])
            calls.append(len(books_in_call))
            result = {b["isbn"]: [{"text": "q", "options": ["a", "b"], "correct": "a"}]
                     for b in books_in_call}
            payload = json.dumps({"candidates": [{"content": {"parts": [{"text": json.dumps(result)}]}}]})
            return payload.encode("utf-8")

        old = fb.BATCH_SIZE
        fb.BATCH_SIZE = 2
        try:
            n = fb.run_distill_stage(self.conn, api_key="fake-key", poster=poster, log=lambda *a: None)
        finally:
            fb.BATCH_SIZE = old
        self.assertEqual(n, 3)
        self.assertEqual(calls, [2, 1])


class TestRenderScanResultUsesEnrichedQuestions(unittest.TestCase):
    def test_enriched_question_renders_same_as_any_other_question(self):
        # No new display code needed for this: an AI-enriched row is
        # just a row whose questions_json happens to hold a better
        # question, same schema, same render path.
        row = {"title": "Moby-Dick", "question_source": fb.ENRICHED_SOURCE,
               "questions_json": json.dumps(
                   [{"text": "Who narrates Moby-Dick?", "options": ["Ishmael", "Ahab"], "correct": "Ishmael"}])}
        lines = bc.render_scan_result(row, 40, 15)
        self.assertTrue(any("narrates" in l for l in lines))
        self.assertTrue(any("Ishmael" in l for l in lines))


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

    def test_books_already_enriched_do_not_count_toward_threshold(self):
        for i in range(bc.FACTS_BATCH_TRIGGER):
            self._register(str(i), f"Book {i}")
            self.conn.execute("UPDATE books SET question_source = ? WHERE isbn = ?",
                              (bc.ENRICHED_SOURCE, str(i)))
        self.conn.commit()
        spawned = []
        fired = bc.maybe_trigger_facts_batch(
            self.conn, spawner=lambda cmd: spawned.append(cmd),
            runner=lambda cmd: type("R", (), {"stdout": ""})())
        self.assertFalse(fired)


if __name__ == "__main__":
    unittest.main()
