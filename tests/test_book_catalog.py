#!/usr/bin/env python3
# Tests for bin/crt-book-catalog.py -- the personal-library-catalog half
# of the Book Game (BOOK-GAME.md's own vision: the registry "doubles as
# a personal library catalog," never actually viewable until now).
import importlib.util
import os
import tempfile
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")

_bg_spec = importlib.util.spec_from_file_location("crt_book_game", os.path.join(BIN_DIR, "crt-book-game.py"))
bg = importlib.util.module_from_spec(_bg_spec)
_bg_spec.loader.exec_module(bg)

_cat_spec = importlib.util.spec_from_file_location("crt_book_catalog", os.path.join(BIN_DIR, "crt-book-catalog.py"))
cat = importlib.util.module_from_spec(_cat_spec)
_cat_spec.loader.exec_module(cat)


def _register(conn, isbn, title, authors, year, lcc_subjects, timestamp):
    book = {"isbn": isbn, "title": title, "authors": authors, "year": year,
            "subjects": lcc_subjects, "raw": {}}
    bg.register_book(conn, book, questions=[], question_source="template", timestamp=timestamp)


class TestListBooks(unittest.TestCase):
    def test_empty_registry_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as d:
            conn = bg.get_db(os.path.join(d, "books.db"))
            self.assertEqual(cat.list_books(conn), [])

    def test_most_recently_scanned_first(self):
        with tempfile.TemporaryDirectory() as d:
            conn = bg.get_db(os.path.join(d, "books.db"))
            _register(conn, "1", "First Book", ["A"], 2000, [], "2026-07-21T10:00:00")
            _register(conn, "2", "Second Book", ["B"], 2001, [], "2026-07-21T11:00:00")
            books = cat.list_books(conn)
            self.assertEqual(books[0]["title"], "Second Book")
            self.assertEqual(books[1]["title"], "First Book")

    def test_fields_present(self):
        with tempfile.TemporaryDirectory() as d:
            conn = bg.get_db(os.path.join(d, "books.db"))
            _register(conn, "1", "Dune", ["Frank Herbert"], 1965, ["Science fiction"], "2026-07-21T10:00:00")
            books = cat.list_books(conn)
            self.assertEqual(books[0]["title"], "Dune")
            self.assertEqual(books[0]["authors"], ["Frank Herbert"])
            self.assertEqual(books[0]["year"], 1965)
            self.assertEqual(books[0]["lcc"], "PS/PR")


class TestRenderCatalogScreen(unittest.TestCase):
    def test_empty_catalog(self):
        lines = cat.render_catalog_screen([])
        self.assertTrue(any("No books" in l for l in lines))

    def test_shows_count_and_latest(self):
        books = [{"title": "Latest Book", "authors": [], "year": None, "lcc": None, "isbn": "2"},
                 {"title": "Older Book", "authors": [], "year": None, "lcc": None, "isbn": "1"}]
        lines = cat.render_catalog_screen(books, width=40)
        self.assertTrue(any("2 book(s)" in l for l in lines))
        self.assertTrue(any("Latest Book" in l for l in lines))

    def test_lines_never_exceed_width(self):
        books = [{"title": "A" * 100, "authors": [], "year": None, "lcc": None, "isbn": "1"}]
        lines = cat.render_catalog_screen(books, width=20)
        self.assertTrue(all(len(l) <= 20 for l in lines))


class TestRenderCatalogFull(unittest.TestCase):
    def test_empty_catalog_message(self):
        report = cat.render_catalog_full([])
        self.assertIn("No books scanned yet", report)

    def test_lists_every_book_with_details(self):
        books = [
            {"title": "Dune", "authors": ["Frank Herbert"], "year": 1965, "lcc": "PS/PR", "isbn": "1"},
            {"title": "Unknown Facts Book", "authors": [], "year": None, "lcc": None, "isbn": "2"},
        ]
        report = cat.render_catalog_full(books)
        self.assertIn("Dune -- Frank Herbert (1965) [PS/PR]", report)
        self.assertIn("Unknown Facts Book -- Unknown author (year unknown) [LCC unknown, best effort]", report)


if __name__ == "__main__":
    unittest.main()
