#!/usr/bin/env python3
# Trivia-fact enrichment batch job (2026-07-28, Zach-directed): "wire up
# the web-based scrape of better facts, non-AI pass for webscrape on
# each, then ai-pass in batches to generate 3-ish high quality facts per
# book for trivia."
#   [rest: vault:crt/header-archaeology-20260817.md]
import argparse
import importlib.util
import json
import os
import sys

BIN_DIR = os.path.dirname(os.path.abspath(__file__))
_bg_spec = importlib.util.spec_from_file_location("crt_book_game", os.path.join(BIN_DIR, "crt-book-game.py"))
bg = importlib.util.module_from_spec(_bg_spec)
_bg_spec.loader.exec_module(bg)

# 2026-07-28, live, Zach-directed ("smaller batch size"): a real 10-book
# batch (30 generated questions) timed out even after the timeout itself
# was widened (see bg.GEMINI_BATCH_TIMEOUT_SECS) -- fewer books per call
# is the other half of that fix, not a substitute for it.
BATCH_SIZE = int(os.environ.get("CRT_BOOK_FACTS_BATCH_SIZE", "4"))


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


# Marks a book's questions_json as already upgraded by the AI distill
# stage (2026-07-28 redesign) -- reuses the existing question_source
# column instead of a new one: 'template' (generate_template_question),
# 'gemini'/'claude' (the pre-existing per-scan batch path), or this.
# Never re-upgrades a book that already has it, same cache-once
# philosophy as everything else in this pipeline.
ENRICHED_SOURCE = "ai-enriched"


def books_needing_distill(conn):
    rows = conn.execute(
        "SELECT isbn, title, authors, year, facts_raw FROM books "
        "WHERE facts_raw IS NOT NULL AND (question_source IS NULL OR question_source != ?)",
        (ENRICHED_SOURCE,),
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
    """Stage 2: AI, batched. Writes real, fact-grounded two-option trivia
    questions directly into questions_json -- REPLACING the generic
    template question (fiction/nonfiction, before/after-a-year), not
    just adding flavor text alongside it (2026-07-28 redesign, after the
    first version showed facts next to the still-generic question and
    Zach caught it: "I'm still getting generic facts?"). Marks
    question_source = ENRICHED_SOURCE so this book is never re-upgraded.
    Returns the count of books that received new questions. Loudly
    no-ops (not a silent skip) when no Gemini key is configured, same
    honesty rule as everywhere else a missing key/credential is handled
    in this project."""
    todo = books_needing_distill(conn)
    log(f"[facts-batch] distill stage: {len(todo)} book(s) not yet AI-enriched")
    if not todo:
        return 0
    key = api_key or bg._load_gemini_key()
    if not key:
        log("[facts-batch] NO GEMINI KEY CONFIGURED (CRT_GEMINI_API_KEY / "
            "~/.crt/gemini.key) -- distill stage cannot run. This is not "
            "silently skipped: the books above still need enriched questions.")
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
            questions = bg.parse_claude_batch_response(response_json, b["isbn"])
            if not questions:
                log(f"[facts-batch] no usable questions returned for {b['isbn']} "
                    f"({b['title']!r}) -- leaving as-is, will retry next run")
                continue
            conn.execute(
                "UPDATE books SET questions_json = ?, question_source = ? WHERE isbn = ?",
                (json.dumps(questions), ENRICHED_SOURCE, b["isbn"]),
            )
            conn.commit()
            log(f"[facts-batch] enriched {b['isbn']} ({b['title']!r}): "
                f"{len(questions)} fact-grounded question(s)")
            processed += 1
    return processed


def _timestamped_log(msg):
    # Only main()'s own default -- run_scrape_stage/run_distill_stage
    # still default to plain print() so tests asserting on exact log
    # text don't have to match a timestamp. This is what actually lands
    # in ~/.crt/facts-batch.log when crt-book-console.py's fire-and-
    #   [rest: vault:crt/header-archaeology-20260817.md]
    import datetime
    print("%s  %s" % (datetime.datetime.now().strftime("%H:%M:%S"), msg))


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
        _timestamped_log(f"dry-run: {scrape_n} book(s) would be scraped, "
                         f"{distill_n} book(s) would be distilled")
        return

    if not args.distill_only:
        run_scrape_stage(conn, log=_timestamped_log)
    if not args.scrape_only:
        run_distill_stage(conn, log=_timestamped_log)


if __name__ == "__main__":
    main()
