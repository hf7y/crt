#!/usr/bin/env python3
# Book Game -- see ../BOOK-GAME.md for full vision/roadmap. This is the
# offline-safe slice registered in .claude/FOCUS.md 2026-07-21: ISBN
# lookup, question generation (template + pluggable batched-Claude
# source), grading/logging, SQLite registry, naive LCC heuristic. Built
# standalone (own CLI), NOT wired into crt-console.sh/crt-secretary.py --
# per BOOK-GAME.md's "standalone first, merge later" direction.
#
# STATUS: NOT hardware-verified. Live scanner input, live mic/STT, and
# console/secretary wiring are all explicitly out of scope for this pass
# (need a hands-on crt-vm session, see BOOK-GAME.md Blockers). Everything
# here is a pure function or a mockable-HTTP/real-sqlite unit, covered by
# tests/test_book_game.py.
#
# Usage:
#   crt-book-game.py --isbn 9780141439518          # full offline round, random source
#   crt-book-game.py --isbn <n> --answer "fiction"  # grade a spoken/typed answer
# Env:
#   CRT_BOOKS_DB (default ~/.crt/books.db)
#   CRT_BOOK_GAME_TRAINING_LOG (default ~/.crt/book-game-training.jsonl)
#   CRT_BOOK_GAME_CLAUDE_RATE (default 0.5) -- fraction of fresh scans that
#     get a Claude-authored question instead of a template one
import argparse
import json
import os
import random
import re
import sqlite3
import time
import urllib.request

DB_PATH = os.path.expanduser(os.environ.get("CRT_BOOKS_DB", "~/.crt/books.db"))
TRAINING_LOG = os.path.expanduser(
    os.environ.get("CRT_BOOK_GAME_TRAINING_LOG", "~/.crt/book-game-training.jsonl"))
CLAUDE_RATE = float(os.environ.get("CRT_BOOK_GAME_CLAUDE_RATE", "0.5"))

OPEN_LIBRARY_URL = "https://openlibrary.org/isbn/{isbn}.json"


# ---------------------------------------------------------------------------
# ISBN -> metadata lookup
# ---------------------------------------------------------------------------

def fetch_book_metadata(isbn, fetcher=None):
    """Look up a book by ISBN. `fetcher` is injectable for tests -- a
    callable(url) -> dict, default does a real HTTP GET against Open
    Library. Raises on lookup failure; callers decide how to handle it."""
    fetcher = fetcher or _http_get_json
    data = fetcher(OPEN_LIBRARY_URL.format(isbn=isbn))
    title = data.get("title", "Unknown title")
    authors = data.get("author_names") or data.get("authors") or []
    if authors and isinstance(authors[0], dict):
        authors = [a.get("name", "Unknown") for a in authors]
    publish_date = data.get("publish_date", "")
    year_match = re.search(r"\d{4}", publish_date or "")
    year = int(year_match.group()) if year_match else None
    subjects = data.get("subjects", [])
    return {
        "isbn": isbn,
        "title": title,
        "authors": authors or ["Unknown"],
        "year": year,
        "subjects": subjects,
        "raw": data,
    }


def _http_get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "crt-book-game/1"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# Question generation: template + pluggable batched-Claude source
# ---------------------------------------------------------------------------

def generate_template_question(book, rng=None):
    """Deterministic 2-option question from a book-facts dict. Picks
    among a few templates based on what facts are available."""
    rng = rng or random
    candidates = []

    if book.get("year"):
        year = book["year"]
        threshold = (year // 10) * 10
        before = threshold + 10 if year >= threshold + 5 else threshold
        correct = "before" if year < before else "after"
        wrong = "after" if correct == "before" else "before"
        candidates.append({
            "text": f"Was \"{book['title']}\" published before or after {before}?",
            "options": [correct, wrong] if rng.random() < 0.5 else [wrong, correct],
            "correct": correct,
        })

    authors = book.get("authors") or []
    if authors and authors[0] != "Unknown":
        first_name = authors[0].split()[0]
        decoy = _decoy_first_name(first_name, rng)
        candidates.append({
            "text": f"Is the author's first name {first_name} or {decoy}?",
            "options": [first_name, decoy] if rng.random() < 0.5 else [decoy, first_name],
            "correct": first_name,
        })

    subjects = [s.lower() for s in (book.get("subjects") or [])]
    if subjects:
        is_fiction = any("fiction" in s for s in subjects)
        correct = "fiction" if is_fiction else "nonfiction"
        wrong = "nonfiction" if is_fiction else "fiction"
        candidates.append({
            "text": f"Is \"{book['title']}\" fiction or nonfiction?",
            "options": [correct, wrong] if rng.random() < 0.5 else [wrong, correct],
            "correct": correct,
        })

    if not candidates:
        # Always-available fallback so the game never has zero questions.
        candidates.append({
            "text": f"Have you read \"{book['title']}\" before, yes or no?",
            "options": ["yes", "no"],
            "correct": None,  # ungradeable content-wise, still a valid STT prompt
        })

    return rng.choice(candidates)


_DECOY_NAMES = ["Ray", "Roy", "Jan", "Jon", "Ann", "Anne", "Erin", "Aaron"]


def _decoy_first_name(real, rng):
    pool = [n for n in _DECOY_NAMES if n.lower() != real.lower()]
    return rng.choice(pool) if pool else "Sam"


def pick_question_source(rng=None, claude_rate=None):
    """The per-book coin flip: 'claude' or 'template'."""
    rng = rng or random
    rate = CLAUDE_RATE if claude_rate is None else claude_rate
    return "claude" if rng.random() < rate else "template"


def build_claude_batch_prompt(books):
    """Pure function: given a list of book-facts dicts, build the single
    batched prompt asking for 3 two-option questions per book, JSON keyed
    by ISBN. Does not call Claude -- just constructs the request payload,
    so this is testable without a live API."""
    books_payload = [
        {
            "isbn": b["isbn"],
            "title": b["title"],
            "authors": b.get("authors"),
            "year": b.get("year"),
            "subjects": (b.get("subjects") or [])[:5],
        }
        for b in books
    ]
    instructions = (
        "For each book below, write exactly 3 two-option multiple-choice "
        "questions about it (each with a correct answer marked). Return ONLY "
        "JSON: {\"<isbn>\": [{\"text\": ..., \"options\": [a, b], \"correct\": ...}, ...]}"
    )
    return {"instructions": instructions, "books": books_payload}


def parse_claude_batch_response(response_json, isbn):
    """Pure function: pull this book's questions out of a parsed batch
    response. Returns [] if the ISBN is missing/malformed rather than
    raising, so one bad entry doesn't take down the whole batch."""
    try:
        entries = response_json.get(isbn, [])
    except AttributeError:
        return []
    questions = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        opts = e.get("options")
        if not (isinstance(opts, list) and len(opts) == 2):
            continue
        questions.append({"text": e.get("text", ""), "options": opts, "correct": e.get("correct")})
    return questions


# ---------------------------------------------------------------------------
# Grading + training-data logging
# ---------------------------------------------------------------------------

def normalize(s):
    s = (s or "").strip().lower()
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


def grade_answer(expected, heard, correct_option):
    """Exact-ish (normalize-then-compare, not fuzzy) grading against the
    two known option strings. Returns a dict with both correctness axes
    tracked separately per BOOK-GAME.md: correct_content (did they know
    the fact) and correct_stt (did the transcription match what they
    presumably said)."""
    norm_expected = normalize(expected)
    norm_heard = normalize(heard)
    norm_correct = normalize(correct_option) if correct_option is not None else None
    correct_stt = norm_expected == norm_heard
    correct_content = (norm_heard == norm_correct) if norm_correct is not None else None
    return {
        "expected": expected,
        "heard": heard,
        "correct_content": correct_content,
        "correct_stt": correct_stt,
    }


def log_training_row(isbn, grade, log_path=None, timestamp=None):
    log_path = log_path or TRAINING_LOG
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    row = {
        "ts": timestamp or _now_iso(),
        "isbn": isbn,
        "expected": grade["expected"],
        "heard": grade["heard"],
        "correct_content": grade["correct_content"],
        "correct_stt": grade["correct_stt"],
    }
    with open(log_path, "a") as f:
        f.write(json.dumps(row) + "\n")
    return row


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


# ---------------------------------------------------------------------------
# LCC: naive subject-keyword heuristic, explicitly best-effort
# ---------------------------------------------------------------------------

LCC_KEYWORD_TABLE = [
    (("fiction", "novel", "short stories"), "PS/PR"),
    (("poetry",), "PS/PR"),
    (("history",), "D"),
    (("biography",), "CT"),
    (("science", "physics", "chemistry", "biology"), "Q"),
    (("mathematics",), "QA"),
    (("philosophy",), "B"),
    (("religion",), "B"),
    (("psychology",), "BF"),
    (("art",), "N"),
    (("music",), "M"),
    (("law",), "K"),
    (("politics", "political science"), "J"),
    (("economics",), "HB"),
    (("technology", "engineering"), "T"),
    (("computer", "computing"), "QA76"),
]


def compute_lcc(subjects):
    """Best-effort, not authoritative -- naive subject-keyword -> LCC-range
    lookup, per BOOK-GAME.md's 2026-07-21 resolved design. Returns None if
    nothing matches (caller should label the result "best effort" when
    displaying it, and treat None as "unknown", not an error)."""
    lowered = [s.lower() for s in (subjects or [])]
    for keywords, lcc in LCC_KEYWORD_TABLE:
        if any(any(kw in s for kw in keywords) for s in lowered):
            return lcc
    return None


# ---------------------------------------------------------------------------
# SQLite registry
# ---------------------------------------------------------------------------

def get_db(db_path=None):
    db_path = db_path or DB_PATH
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS books (
            isbn TEXT PRIMARY KEY,
            title TEXT,
            authors TEXT,
            year INTEGER,
            subjects TEXT,
            raw_json TEXT,
            questions_json TEXT,
            question_source TEXT,
            lcc TEXT,
            label_printed INTEGER DEFAULT 0,
            first_scanned TEXT
        )
    """)
    conn.commit()
    return conn


def register_book(conn, book, questions=None, question_source=None, timestamp=None):
    """Insert if new (cache: never overwrites an existing row's questions
    on re-scan), else return the existing row untouched."""
    existing = get_book(conn, book["isbn"])
    if existing is not None:
        return existing
    lcc = compute_lcc(book.get("subjects"))
    conn.execute(
        "INSERT INTO books (isbn, title, authors, year, subjects, raw_json, "
        "questions_json, question_source, lcc, label_printed, first_scanned) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
        (
            book["isbn"], book["title"], json.dumps(book.get("authors")),
            book.get("year"), json.dumps(book.get("subjects")),
            json.dumps(book.get("raw", {})), json.dumps(questions or []),
            question_source, lcc, timestamp or _now_iso(),
        ),
    )
    conn.commit()
    return get_book(conn, book["isbn"])


def get_book(conn, isbn):
    row = conn.execute("SELECT * FROM books WHERE isbn = ?", (isbn,)).fetchone()
    if row is None:
        return None
    cols = [d[0] for d in conn.execute("SELECT * FROM books LIMIT 0").description]
    return dict(zip(cols, row))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Book Game (offline-safe slice)")
    parser.add_argument("--isbn", required=True)
    parser.add_argument("--answer", help="spoken/typed answer to grade against a pending question")
    args = parser.parse_args()

    conn = get_db()
    existing = get_book(conn, args.isbn)
    if existing is None:
        book = fetch_book_metadata(args.isbn)
        source = pick_question_source()
        # Live Claude-batch calls need a real crt-vm session (see
        # BOOK-GAME.md); this standalone CLI always uses the template
        # path so a fresh scan never blocks on network/API access, but
        # still records which source *would* have been used.
        question = generate_template_question(book)
        row = register_book(conn, book, questions=[question], question_source=source)
        print(f"Scanned: {row['title']} ({row['lcc'] or 'LCC unknown, best effort'})")
        questions = json.loads(row["questions_json"])
        if questions:
            print(f"Q: {questions[0]['text']} [{' / '.join(questions[0]['options'])}]")
        return

    print(f"Already registered: {existing['title']}")
    if args.answer:
        questions = json.loads(existing["questions_json"])
        if not questions:
            print("No question on file for this book.")
            return
        q = questions[0]
        grade = grade_answer(expected=q.get("correct"), heard=args.answer, correct_option=q.get("correct"))
        log_training_row(args.isbn, grade)
        print(f"correct_content={grade['correct_content']} correct_stt={grade['correct_stt']}")


if __name__ == "__main__":
    main()
