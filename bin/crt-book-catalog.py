#!/usr/bin/env python3
# The personal-library-catalog half of the Book Game (BOOK-GAME.md's own
# vision: the registry "documents the books for safe keeping... doubles
# as a personal library catalog, independent of the game"). That vision
# line was never actually implemented -- books.db has held every scanned
#   [rest: vault:crt/header-archaeology-20260817.md]
import importlib.util
import json
import os
import sys

BIN_DIR = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("crt_book_game", os.path.join(BIN_DIR, "crt-book-game.py"))
bg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bg)

SCREEN_WIDTH = int(os.environ.get("CRT_PAGER_WIDTH", "40"))


def list_books(conn):
    """Pure-ish (only reads conn): every registered book, most recently
    scanned first -- the actual catalog. Returns a list of dicts, not
    raw sqlite rows, so callers/tests don't need column-index knowledge."""
    rows = conn.execute(
        "SELECT isbn, title, authors, year, lcc, first_scanned FROM books "
        "ORDER BY first_scanned DESC"
    ).fetchall()
    books = []
    for isbn, title, authors_json, year, lcc, first_scanned in rows:
        authors = json.loads(authors_json or "[]")
        books.append({
            "isbn": isbn, "title": title, "authors": authors,
            "year": year, "lcc": lcc, "first_scanned": first_scanned,
        })
    return books


def render_catalog_screen(books, width=None):
    """Pure function: a short CRT-width summary -- total count and the
    most recently scanned title, not the full list (no room for that on
    a 40-col screen; that's what print-all is for)."""
    width = width or SCREEN_WIDTH
    if not books:
        return ["No books in the catalog yet."[:width]]
    lines = [f"{len(books)} book(s) in your library." [:width]]
    most_recent = books[0]
    lines.append(f"Latest: {most_recent['title']}"[:width])
    return lines


def render_catalog_full(books):
    """Pure function: the full printable catalog listing, most recently
    scanned first -- title, author(s), year, LCC (best-effort, per
    BOOK-GAME.md's own labeling convention -- never shown as if it were
    authoritative)."""
    if not books:
        return "Book Catalog\n============\n\nNo books scanned yet.\n"
    lines = ["Book Catalog", "============", ""]
    for b in books:
        authors = ", ".join(b["authors"]) if b["authors"] else "Unknown author"
        year = b["year"] if b["year"] else "year unknown"
        lcc = b["lcc"] if b["lcc"] else "LCC unknown, best effort"
        lines.append(f"{b['title']} -- {authors} ({year}) [{lcc}]")
    return "\n".join(lines) + "\n"


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "screen"
    conn = bg.get_db()
    books = list_books(conn)

    if mode == "screen":
        for line in render_catalog_screen(books):
            print(line)
    elif mode == "print-all":
        print(render_catalog_full(books), end="")
    else:
        sys.stderr.write("usage: crt-book-catalog.py [screen|print-all]\n")
        sys.exit(2)


if __name__ == "__main__":
    main()
