#!/usr/bin/env python3
"""crt-book-blurb.py -- scan a book, get one line about it (crt#122)."""
import hashlib
import importlib.util
import json
import os
import sys

BIN_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_sibling(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(BIN_DIR, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bg = _load_sibling("crt_book_game_for_blurb", "crt-book-game.py")
scan_line = _load_sibling("crt_scan_line_for_blurb", "crt_scan_line.py")


LINE_WIDTH = bg.FALLBACK_WIDTH  # 40, not MAX_CONTENT_WIDTH (30, centered dialog only)


def blurb_line(title, quote):
    quote = (quote or "").strip()
    text = f"{title} -- {quote}" if quote else title
    if len(text) <= LINE_WIDTH:
        return text
    return text[: LINE_WIDTH - 3].rstrip() + "..."


def lookup_blurb(isbn, conn, fetcher=None, quote_fetcher=None, rng=None):
    existing = bg.get_book(conn, isbn)
    if existing is not None:
        quote = existing["quote"] or bg.extract_quote(json.loads(existing["raw_json"] or "{}"))
        return blurb_line(existing["title"], quote)
    book = bg.fetch_book_metadata(isbn, fetcher=fetcher)
    quote = bg.extract_quote(book.get("raw")) or bg.scrape_quote(
        book["title"], fetcher=quote_fetcher, rng=rng)
    if not quote:
        idx = int(hashlib.sha256(isbn.encode()).hexdigest(), 16) % len(bg.FALLBACK_QUOTES)
        quote = bg.FALLBACK_QUOTES[idx]
    return blurb_line(book["title"], quote)


def safe_blurb(isbn, conn):
    try:
        return lookup_blurb(isbn, conn)
    except Exception:
        return f"couldn't find that book. (isbn {isbn})"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    conn = bg.get_db()
    isbns = argv if argv else (line.strip() for line in sys.stdin)
    for candidate in isbns:
        if not scan_line.is_isbn_like(candidate):
            continue
        print(safe_blurb(candidate, conn))
    return 0


if __name__ == "__main__":
    sys.exit(main())
