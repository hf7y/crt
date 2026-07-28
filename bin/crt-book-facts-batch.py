#!/usr/bin/env python3
# Trivia-fact enrichment batch job (2026-07-28, Zach-directed): "wire up
# the web-based scrape of better facts, non-AI pass for webscrape on
# each, then ai-pass in batches to generate 3-ish high quality facts per
# book for trivia."
#
# Two independent stages, run in order each invocation, each cache-once
# (never redoes a book that already has a value in the relevant column --
# same philosophy as quote/lcc/questions_json):
#
#   1. SCRAPE (non-AI): every registered book with facts_raw IS NULL gets
#      a Wikipedia summary-API lookup by title (bin/crt-book-game.py's
#      fetch_wikipedia_extract/extract_fact_candidates) -- cheap, no API
#      key, no rate limit that matters at this scale. Cached into
#      facts_raw regardless of whether anything useful came back (an
#      empty list is itself a cached "nothing found", not a retry-forever
#      signal -- same convention as quote's fallback chain).
#
#   2. DISTILL (AI, batched): every book with facts_raw IS NOT NULL and
#      facts_json IS NULL gets grouped into batches of CRT_BOOK_FACTS_
#      BATCH_SIZE and sent through ONE Gemini call per batch (bin/
#      crt-book-game.py's build_facts_batch_prompt/call_gemini_batch/
#      parse_facts_batch_response) asking for exactly 3 high-quality
#      facts per book, grounded in each book's own facts_raw candidates.
#      Skipped entirely (loud, not silent) if no Gemini key is
#      configured -- see bin/crt-book-game.py's _load_gemini_key.
#
# STATUS: NOT hardware-verified past this pass's own live scrape-stage
# run on potato's real registered books. The AI/distill stage is
# regression-tested with an injected fake poster but has never run
# against the real Gemini API (no key configured on potato as of this
# writing) -- treat its live behavior as unverified until a key exists
# and this has actually been run with one.
#
# Usage:
#   crt-book-facts-batch.py               # both stages
#   crt-book-facts-batch.py --scrape-only  # stage 1 only
#   crt-book-facts-batch.py --distill-only # stage 2 only
#   crt-book-facts-batch.py --dry-run      # report what WOULD run, do nothing
#
# Env:
#   CRT_BOOK_FACTS_BATCH_SIZE (default 10) -- books per Gemini call
import argparse
import importlib.util
import json
import os
import sys

BIN_DIR = os.path.dirname(os.path.abspath(__file__))
_bg_spec = importlib.util.spec_from_file_location("crt_book_game", os.path.join(BIN_DIR, "crt-book-game.py"))
bg = importlib.util.module_from_spec(_bg_spec)
_bg_spec.loader.exec_module(bg)

BATCH_SIZE = int(os.environ.get("CRT_BOOK_FACTS_BATCH_SIZE", "10"))


def books_needing_scrape(conn):
    rows = conn.execute("SELECT isbn, title FROM books WHERE facts_raw IS NULL").fetchall()
    return [{"isbn": r[0], "title": r[1]} for r in rows]


def run_scrape_stage(conn, fetcher=None, log=print):
    """Stage 1: non-AI. Returns the count of books processed (whether or
    not anything useful was found -- an empty-candidates result still
    counts as processed, since it's cached as such)."""
    todo = books_needing_scrape(conn)
    log(f"[facts-batch] scrape stage: {len(todo)} book(s) missing facts_raw")
    processed = 0
    for b in todo:
        extract = bg.fetch_wikipedia_extract(b["title"], fetcher=fetcher)
        candidates = bg.extract_fact_candidates(extract) if extract else []
        conn.execute("UPDATE books SET facts_raw = ? WHERE isbn = ?",
                     (json.dumps(candidates), b["isbn"]))
        conn.commit()
        log(f"[facts-batch] scraped {b['isbn']} ({b['title']!r}): "
            f"{len(candidates)} candidate sentence(s)")
        processed += 1
    return processed


def books_needing_distill(conn):
    rows = conn.execute(
        "SELECT isbn, title, authors, year, facts_raw FROM books "
        "WHERE facts_raw IS NOT NULL AND facts_json IS NULL"
    ).fetchall()
    out = []
    for isbn, title, authors, year, facts_raw in rows:
        out.append({
            "isbn": isbn, "title": title,
            "authors": json.loads(authors) if authors else [],
            "year": year,
            "facts_raw": json.loads(facts_raw) if facts_raw else [],
        })
    return out


def _chunks(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def run_distill_stage(conn, api_key=None, poster=None, log=print):
    """Stage 2: AI, batched. Returns the count of books that received
    facts_json. Loudly no-ops (not a silent skip) when no Gemini key is
    configured, same honesty rule as everywhere else a missing key/
    credential is handled in this project."""
    todo = books_needing_distill(conn)
    log(f"[facts-batch] distill stage: {len(todo)} book(s) missing facts_json")
    if not todo:
        return 0
    key = api_key or bg._load_gemini_key()
    if not key:
        log("[facts-batch] NO GEMINI KEY CONFIGURED (CRT_GEMINI_API_KEY / "
            "~/.crt/gemini.key) -- distill stage cannot run. This is not "
            "silently skipped: the books above still need facts_json.")
        return 0

    processed = 0
    for batch in _chunks(todo, BATCH_SIZE):
        prompt = bg.build_facts_batch_prompt(batch)
        try:
            response_json = bg.call_gemini_batch(prompt, api_key=key, poster=poster)
        except Exception as e:
            log(f"[facts-batch] Gemini batch call failed for "
                f"{[b['isbn'] for b in batch]}: {e}")
            continue
        for b in batch:
            facts = bg.parse_facts_batch_response(response_json, b["isbn"])
            if not facts:
                log(f"[facts-batch] no usable facts returned for {b['isbn']} "
                    f"({b['title']!r}) -- leaving facts_json NULL, will retry "
                    f"next run")
                continue
            conn.execute("UPDATE books SET facts_json = ? WHERE isbn = ?",
                         (json.dumps(facts), b["isbn"]))
            conn.commit()
            log(f"[facts-batch] distilled {b['isbn']} ({b['title']!r}): "
                f"{len(facts)} fact(s)")
            processed += 1
    return processed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scrape-only", action="store_true")
    parser.add_argument("--distill-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true",
                        help="report counts, do not fetch/call/write anything")
    args = parser.parse_args()

    conn = bg.get_db()

    if args.dry_run:
        scrape_n = len(books_needing_scrape(conn))
        distill_n = len(books_needing_distill(conn))
        print(f"[facts-batch] dry-run: {scrape_n} book(s) would be scraped, "
              f"{distill_n} book(s) would be distilled")
        return

    if not args.distill_only:
        run_scrape_stage(conn)
    if not args.scrape_only:
        run_distill_stage(conn)


if __name__ == "__main__":
    main()
