#!/usr/bin/env python3
# Summarizes Book Game progress toward its actual end-goal
# (.claude/FOCUS.md's 2026-07-21 statement: idle-bait -> scan -> question
# -> spoken answer -> STT training log is one funnel) -- how many books
# have been scanned, how many trivia rounds actually got a spoken answer,
# and critically, the STT-training payoff itself: how often the local
# grading agreed with what was actually said (correct_stt) vs. how often
# the room's mic/whisper pipeline is still getting it wrong. That second
# number is the entire point of this subsystem existing at all
# (STT-MECHANISM.md/CLAUDE.md's "improve STT inference over time"), so it
# gets top billing here, not buried under book trivia scores.
#
# Zero Claude/API calls -- pure local reads of books.db and
# book-game-training.jsonl, same "90% offline supervisor" spirit as
# crt-present-morning-report.py (SUPERVISOR.md).
#
# STATUS: NOT hardware-verified against real training data (no real scan
# has been graded yet as of this writing) -- summarize_* functions are
# pure/covered by tests/test_book_game_stats.py against synthetic
# books.db + training.jsonl fixtures.
#
# Usage:
#   crt-book-game-stats.py screen          # CRT-width one-liner summary
#   crt-book-game-stats.py print-all       # full text for the printer
#   crt-book-game-stats.py export-fixups   # candidate bin/stt-fixups.json
#                                            entries generated from
#                                            repeated STT mismatches
import importlib.util
import json
import os
import sys
from collections import Counter

BIN_DIR = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("crt_book_game", os.path.join(BIN_DIR, "crt-book-game.py"))
bg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bg)

TRAINING_LOG = os.path.expanduser(os.environ.get("CRT_BOOK_GAME_TRAINING_LOG", "~/.crt/book-game-training.jsonl"))
SCREEN_WIDTH = int(os.environ.get("CRT_PAGER_WIDTH", "40"))


def load_training_rows(log_path=None):
    """Reads book-game-training.jsonl (one JSON object per line, written
    by crt-book-game.py's log_training_row()) into a list of dicts.
    Missing file -> empty list (nothing graded yet, not an error).
    Malformed lines are skipped, not fatal -- one bad line shouldn't hide
    every other real training row."""
    log_path = log_path or TRAINING_LOG
    rows = []
    if not os.path.exists(log_path):
        return rows
    with open(log_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def summarize_books(conn):
    """Pure-ish (only reads conn): book-count/source-mix stats."""
    total = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
    template = conn.execute(
        "SELECT COUNT(*) FROM books WHERE question_source = 'template'").fetchone()[0]
    claude = conn.execute(
        "SELECT COUNT(*) FROM books WHERE question_source = 'claude'").fetchone()[0]
    return {"total": total, "template_questions": template, "claude_questions": claude}


def summarize_training(rows):
    """Pure function: the actual STT-training payoff numbers -- see file
    header for why correct_stt gets top billing over correct_content.
    Returns a dict with counts and rates (None rate if there's no data
    yet, never a divide-by-zero).

    correct_stt is three-valued since 2026-07-25 (grade_answer gained the
    option list; None means "no options recorded, so nothing to judge the
    transcription against"). stt_accuracy is therefore over the rows where
    it is KNOWN, exactly as content_accuracy already was -- dividing by
    len(rows) would let an unjudgeable round read as a transcription
    failure, which is the whole class of error that change fixed."""
    total = len(rows)
    stt_known = [r for r in rows if r.get("correct_stt") is not None]
    stt_correct = sum(1 for r in stt_known if r.get("correct_stt") is True)
    content_known = [r for r in rows if r.get("correct_content") is not None]
    content_correct = sum(1 for r in content_known if r.get("correct_content") is True)
    mismatches = [r for r in rows if r.get("correct_stt") is False]
    return {
        "total_rounds": total,
        "stt_correct": stt_correct,
        "stt_known": len(stt_known),
        "stt_accuracy": (stt_correct / len(stt_known)) if stt_known else None,
        "content_correct": content_correct,
        "content_known": len(content_known),
        "content_accuracy": (content_correct / len(content_known)) if content_known else None,
        "mismatches": mismatches,
    }


def render_screen_summary(book_stats, training_stats, width=None):
    """Pure function: a short CRT-width summary, book count first, STT
    accuracy second (the actual point of the feature)."""
    width = width or SCREEN_WIDTH
    lines = [f"Book Game: {book_stats['total']} book(s) scanned"]
    if training_stats["total_rounds"] == 0:
        lines.append("No spoken answers graded yet.")
    elif training_stats["stt_accuracy"] is None:
        # Rounds exist but none of them recorded an option list to judge the
        # transcription against (pre-2026-07-25 rows can also land here).
        # Saying "0%" would be a lie in the direction that panics people.
        lines.append(f"{training_stats['total_rounds']} answer(s) graded, STT accuracy n/a")
    else:
        acc = training_stats["stt_accuracy"]
        lines.append(f"{training_stats['total_rounds']} answer(s) graded, STT accuracy {acc:.0%}")
    return [ln[:width] for ln in lines]


def render_full_report(book_stats, training_stats):
    """Pure function: the full printable text -- includes every logged
    mismatch (expected vs. heard) since THAT list is the actual STT
    training artifact this whole subsystem exists to produce."""
    lines = [
        "Book Game Report",
        "=================",
        "",
        f"Books scanned: {book_stats['total']}",
        f"  question source -- template: {book_stats['template_questions']}, "
        f"claude: {book_stats['claude_questions']}",
        "",
        f"Trivia rounds graded: {training_stats['total_rounds']}",
    ]
    if training_stats["total_rounds"]:
        acc = training_stats["stt_accuracy"]
        # "matched what was expected" was the old, wrong wording: expected is
        # the CORRECT option, so that phrasing described a trivia score
        # wearing an STT label. What is actually measured is whether the
        # transcription landed on one of the options the person was offered.
        lines.append(f"  STT accuracy (heard was one of the offered options): "
                      f"{training_stats['stt_correct']}/{training_stats['stt_known']}"
                      + (f" ({acc:.0%})" if acc is not None else " (n/a)"))
        if training_stats["content_known"]:
            cacc = training_stats["content_accuracy"]
            lines.append(f"  Trivia correctness (ignoring STT errors): "
                          f"{training_stats['content_correct']}/{training_stats['content_known']}"
                          + (f" ({cacc:.0%})" if cacc is not None else ""))
        if training_stats["mismatches"]:
            lines.append("")
            lines.append("STT mismatches (expected -> heard), the actual training data:")
            for m in training_stats["mismatches"]:
                lines.append(f"  {m.get('isbn', '?')}: {m.get('expected')!r} -> {m.get('heard')!r}")
    else:
        lines.append("  Nothing graded yet -- scan a book and speak an answer to start.")
    return "\n".join(lines) + "\n"


def generate_candidate_fixups(mismatches, min_repeats=2):
    """Pure function: turns the Book Game's logged (expected, heard) STT
    mismatches into candidate bin/stt-fixups.json entries -- the exact
    shape that file already uses (heard-fragment key -> {intent, type,
    confidence, note}, see STT-MECHANISM.md's garble taxonomy), so a
    human can review and literally copy accepted ones straight in. Only
    surfaces a (heard, expected) pair once it's recurred at least
    `min_repeats` times -- a single mismatch could just be one-off noise;
    stt-fixups.json's own convention is "append as patterns are
    confirmed," and repetition is the cheapest local signal that a
    mishear is a real, consistent pattern rather than a fluke. Always
    `confidence: candidate`, never `confirmed` -- this script has no way
    to actually verify a fixup live, only a human calibration session can
    do that (same bar the real file's existing entries were held to)."""
    pair_counts = Counter()
    for m in mismatches:
        heard = (m.get("heard") or "").strip().lower()
        expected = (m.get("expected") or "").strip().lower()
        if heard and expected and heard != expected:
            pair_counts[(heard, expected)] += 1
    candidates = {}
    for (heard, expected), count in pair_counts.items():
        if count >= min_repeats:
            candidates[heard] = {
                "intent": expected,
                "type": "book-game-observed",
                "confidence": "candidate",
                "note": f"seen {count}x as a Book Game trivia-answer mismatch -- "
                        f"needs human confirmation before treating as confirmed",
            }
    return candidates


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "screen"
    conn = bg.get_db()
    book_stats = summarize_books(conn)
    training_stats = summarize_training(load_training_rows())

    if mode == "screen":
        for line in render_screen_summary(book_stats, training_stats):
            print(line)
    elif mode == "print-all":
        print(render_full_report(book_stats, training_stats), end="")
    elif mode == "export-fixups":
        candidates = generate_candidate_fixups(training_stats["mismatches"])
        print(json.dumps(candidates, indent=2, sort_keys=True))
    else:
        sys.stderr.write("usage: crt-book-game-stats.py [screen|print-all|export-fixups]\n")
        sys.exit(2)


if __name__ == "__main__":
    main()
