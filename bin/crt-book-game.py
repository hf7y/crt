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
import hashlib
import json
import os
import random
import re
import shutil
import sqlite3
import sys
import textwrap
import time
import urllib.parse
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
    Library. Raises on lookup failure; callers decide how to handle it.

    Author extraction handles THREE real shapes confirmed live against
    Open Library's actual ISBN/edition endpoint (2026-07-21 branch
    investigation into "trivia always asks the year question, never the
    author one, and author always shows as Unknown"):
      1. `"author": ["Last, First[, dates].", ...]` -- the common real
         shape this endpoint actually returns, previously NOT CHECKED AT
         ALL (code only looked for "author_names"/"authors", neither of
         which this endpoint uses for this shape) -- this was the
         confirmed root cause of authors always coming back ["Unknown"],
         which in turn meant generate_template_question()'s author-name
         candidate could never fire (it requires authors[0] != "Unknown"),
         starving most real scans down to only the year-based question.
      2. `"authors": [{"key": "/authors/OL...A"}]` -- a bare reference
         with NO embedded name, confirmed live too (needs a second API
         call to `/authors/OL...A.json` to resolve a name). NOT resolved
         here -- an extra network hop per scan is a real latency/
         reliability tradeoff, deliberately not added in this pass; falls
         back to "Unknown" same as before, so this shape is a known,
         documented remaining limitation, not silently claimed as fixed.
      3. No author field present at all -- genuinely absent upstream,
         nothing to extract.
    "Last, First[, dates]." entries are reformatted to "First Last" via
    _clean_author_name() so both display and the author-first-name
    template question read naturally instead of showing "Orwell," (a
    trailing comma from naively splitting the raw "Last, First" string)."""
    fetcher = fetcher or _http_get_json
    data = fetcher(OPEN_LIBRARY_URL.format(isbn=isbn))
    title = data.get("title", "Unknown title")
    authors_raw = data.get("author_names") or data.get("authors") or data.get("author") or []
    if authors_raw and isinstance(authors_raw[0], dict):
        authors_raw = [a.get("name", "Unknown") for a in authors_raw]
    authors = [_clean_author_name(a) for a in authors_raw if a] or ["Unknown"]
    publish_date = data.get("publish_date", "")
    year_match = re.search(r"\d{4}", publish_date or "")
    year = int(year_match.group()) if year_match else None
    subjects = data.get("subjects", [])
    return {
        "isbn": isbn,
        "title": title,
        "authors": authors,
        "year": year,
        "subjects": subjects,
        "raw": data,
    }


def _clean_author_name(raw):
    """Pure function: Open Library's edition/ISBN endpoint's `"author"`
    field commonly gives 'Last, First Middle, dates.' (e.g. 'Orwell,
    George, 1903-1950.', confirmed live) -- reformat to 'First Middle
    Last' so both display and generate_template_question()'s first-name
    extraction (which assumes "First Last" word order) work naturally.
    Falls back to the raw string unchanged if it doesn't contain a comma
    (already "First Last" shape, or an org/unknown-format name)."""
    raw = raw.strip()
    if "," not in raw:
        return raw
    parts = [p.strip() for p in raw.split(",")]
    last = parts[0]
    first = parts[1].rstrip(".").strip() if len(parts) > 1 else ""
    return f"{first} {last}" if first else last


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
    """Writes one graded round to book-game-training.jsonl -- this IS the
    actual STT training data this whole subsystem exists to produce
    (.claude/FOCUS.md's 2026-07-21 end-goal), not an incidental log.
    Still best-effort on the write itself (os.makedirs/open can fail --
    disk full, permission issue): unlike every OTHER logging call in this
    project (crt-secretary.py's log_fallthrough, crt-book-answer-
    listen.py's announce), this one previously had NO try/except at all,
    so a single failed write would crash whichever caller invoked it --
    crt-book-answer-listen.py's main() loop (silently killing grading
    for the rest of that process's life, the exact same invisible-
    failure shape as this session's last three bug fixes) or this file's
    own CLI. Prints a visible warning to stderr on failure (both known
    callers run in a foreground tmux pane by default, unlike the fully-
    backgrounded stdin_reader thread those other fixes had to solve for)
    -- still returns the computed row either way, since the grade data
    itself is valid even if persisting it failed, and callers like
    format_result_line() only need the dict, not a successful write."""
    log_path = log_path or TRAINING_LOG
    row = {
        "ts": timestamp or _now_iso(),
        "isbn": isbn,
        "expected": grade["expected"],
        "heard": grade["heard"],
        "correct_content": grade["correct_content"],
        "correct_stt": grade["correct_stt"],
    }
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a") as f:
            f.write(json.dumps(row) + "\n")
    except OSError as e:
        print(f"[crt-book-game] WARNING: failed to write training row to "
              f"{log_path}: {e} -- this round's STT training data was lost.",
              file=sys.stderr)
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
    """Opens books.db. WAL mode + an explicit busy_timeout matter here
    specifically because this is no longer a single-process database:
    crt-book-console.py, crt-book-answer-listen.py, crt-book-idle-bait.py,
    crt-book-game-stats.py (including via crt-secretary.py's
    book_game_stats playbook), and this CLI can all open the same file
    concurrently now (a real architecture change across today's passes,
    not a hypothetical). Default rollback-journal mode blocks ANY reader
    while a writer holds the lock and vice versa; WAL lets readers
    proceed concurrently with a single writer, which is exactly this
    project's actual access pattern (frequent short reads for
    display/stats, occasional short writes on a scan/grade). `timeout`
    (already the sqlite3 module's own busy-retry window, not a new
    mechanism) is bumped from the 5s default to 10s as extra headroom
    -- WAL should make contention rare, this is a safety margin, not
    the primary fix."""
    db_path = db_path or DB_PATH
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL")
    _init_schema(conn)
    return conn


def _init_schema(conn, retries=5):
    """CREATE TABLE/ALTER TABLE can still transiently collide even under
    WAL mode when several fresh connections race to initialize the SAME
    brand-new database file at once (confirmed by a real, if narrow,
    flaky 'database is locked' error under
    tests/test_book_game.py::TestConcurrentAccess's 10-thread stress
    test -- WAL fixes ongoing read/write contention, it doesn't make
    concurrent schema-creation atomic across connections). This is a
    fresh-install-only edge case in practice (the file exists after the
    very first scan ever), but the honest fix is a short retry with
    backoff on that specific, well-understood transient condition, not
    silently hoping it doesn't happen."""
    for attempt in range(retries):
        try:
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
                    quote TEXT,
                    label_printed INTEGER DEFAULT 0,
                    first_scanned TEXT
                )
            """)
            existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(books)")}
            if "quote" not in existing_cols:
                conn.execute("ALTER TABLE books ADD COLUMN quote TEXT")
            conn.commit()
            return
        except sqlite3.OperationalError:
            if attempt == retries - 1:
                raise
            time.sleep(0.1 * (attempt + 1))


def register_book(conn, book, questions=None, question_source=None, timestamp=None, quote=None):
    """Insert if new (cache: never overwrites an existing row's questions
    on re-scan), else return the existing row untouched. `quote` is
    computed ONCE here at registration time (not re-fetched on re-scan,
    same cache-once philosophy as questions/LCC) -- pass a pre-scraped
    value in, or leave None to fall back to extract_quote()/the static
    pool at read time (pick_idle_quote handles that fallback chain)."""
    existing = get_book(conn, book["isbn"])
    if existing is not None:
        return existing
    lcc = compute_lcc(book.get("subjects"))
    conn.execute(
        "INSERT INTO books (isbn, title, authors, year, subjects, raw_json, "
        "questions_json, question_source, lcc, quote, label_printed, first_scanned) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
        (
            book["isbn"], book["title"], json.dumps(book.get("authors")),
            book.get("year"), json.dumps(book.get("subjects")),
            json.dumps(book.get("raw", {})), json.dumps(questions or []),
            question_source, lcc, quote, timestamp or _now_iso(),
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
# Screen real estate: width/height variables, centering
# ---------------------------------------------------------------------------
# Same env-override > real-terminal-size > CLAUDE.md-40x15-fallback pattern
# as bin/crt-pager.py -- kept as a small local copy (not an import) because
# bin/ scripts here aren't packaged as a shared library; see BOOK-GAME-
# STYLE.md "Screen real estate" for the full rationale and the layout
# rules built on top of these two numbers.
FALLBACK_WIDTH = 40
FALLBACK_HEIGHT = 15
# HARD RULE (2026-07-21, Zach): actual text content never spans more
# than this many characters, even on a wider screen -- readability on
# the real tube, confirmed live, not a stylistic choice. Screen LINES
# still get padded to the full detected/fallback width for a consistent
# layout; this only caps the text itself before centering.
MAX_CONTENT_WIDTH = 30


def detect_screen_size():
    env_w = os.environ.get("CRT_BOOK_GAME_WIDTH")
    env_h = os.environ.get("CRT_BOOK_GAME_HEIGHT")
    if env_w and env_h:
        return int(env_w), int(env_h)
    try:
        cols, lines = shutil.get_terminal_size(fallback=(FALLBACK_WIDTH, FALLBACK_HEIGHT))
    except OSError:
        cols, lines = FALLBACK_WIDTH, FALLBACK_HEIGHT
    return int(env_w) if env_w else cols, int(env_h) if env_h else lines


def center_text(text, width):
    """Pure centering helper -- pads `text` with leading/trailing spaces
    to `width`. Truncates (never wraps) text longer than width, since a
    single over-length line is a caller bug, not something this helper
    should silently multi-line."""
    if len(text) >= width:
        return text[:width]
    pad = width - len(text)
    left = pad // 2
    right = pad - left
    return (" " * left) + text + (" " * right)


def render_question_screen(book_title, question, width=None, height=None):
    """Full-screen layout for one question round, per BOOK-GAME-STYLE.md's
    'questions centered' rule -- title top, question + options centered
    in the vertical middle, everything else blank padding. Pure function:
    returns a list of exactly `height` strings, each exactly `width`
    chars, no ANSI codes (callers wrap in color separately, see
    wrap_color) so this is trivially diffable in tests.

    HARD RULE (2026-07-21, Zach): actual text content never exceeds
    MAX_CONTENT_WIDTH (30) characters, even on a wider screen -- lines
    are still padded to the full `width` for a consistent screen size,
    but wrapping/truncation of the title/question/options text itself is
    computed against `min(width, MAX_CONTENT_WIDTH)`, not the raw
    `width`."""
    width = width or FALLBACK_WIDTH
    height = height or FALLBACK_HEIGHT
    content_width = min(width, MAX_CONTENT_WIDTH)
    lines = [" " * width for _ in range(height)]

    title_line = center_text(book_title[: content_width - 2], width)
    q_lines = textwrap.wrap(question["text"], content_width - 2) or [""]
    options_line = center_text(" / ".join(question["options"])[:content_width], width)

    block = [center_text(l, width) for l in q_lines] + [" " * width, options_line]
    block_start = max(0, (height - len(block)) // 2)

    lines[0] = title_line
    for i, l in enumerate(block):
        row = block_start + i
        if 0 <= row < height:
            lines[row] = l
    return lines


# ---------------------------------------------------------------------------
# Color palette: register-matched, CRT-safe (see BOOK-GAME-STYLE.md)
# ---------------------------------------------------------------------------
# CRT PERSISTENT LIMITATION, flag every time this file is touched: this is
# an analog composite/RF display, not a digital one. Fully-saturated
# primaries -- red, green, and blue, AT ANY INTENSITY (not just the
# bright/bold 91/92/94 variants -- confirmed live 2026-07-21 by Zach:
# even standard-intensity 31/32/34 render badly) -- are exactly the
# colors that bleed/smear/ring on a real CRT tube fed a composite or RF
# signal (limited chroma bandwidth vs. luma, the same reason old
# broadcast graphics avoided saturated primary text). This is a hardware
# constraint of the device this project targets, not a taste preference.
#
# HARD RULE (2026-07-21, Zach, confirmed live -- do not reintroduce):
# never use ANSI codes 31, 32, 34, 91, 92, or 94 anywhere in this
# project's screen output, at any boldness/dimness. Only the secondary/
# mixed hues -- yellow (33), magenta (35), cyan (36), white (37) -- plus
# dim/bold modifiers on THOSE, are CRT-safe. Enforced mechanically by
# tests/test_book_game.py's test_no_primary_rgb_codes_in_palette (not
# just a comment -- a future palette edit that violates this will fail
# the test suite). Same flag lives in CLAUDE.md so it survives outside
# this one file.
#
# Palette below stays within that safe set only -- previously
# COLOR_CORRECT/COLOR_WRONG used plain green(32)/red(31), which violated
# this exact rule; reassigned to white/magenta instead, still visually
# distinct per register.
COLOR_QUESTION = "\033[33m"    # warm/curious register -- a question posed
COLOR_CORRECT = "\033[1;37m"   # content/settled -- got it right (bold white, was green -- fixed)
COLOR_WRONG = "\033[35m"       # clipped -- got it wrong (magenta, was red -- fixed)
COLOR_QUOTE = "\033[2;36m"     # wistful/quiet -- idle-bait quote (dim cyan)
COLOR_TITLE = "\033[36m"       # ordinary/curious -- book title, same cyan as idle-teaser
COLOR_RESET = "\033[0m"


def wrap_color(text, color_code):
    return color_code + text + COLOR_RESET


# ---------------------------------------------------------------------------
# ASCII art library: small curated set, book-themed
# ---------------------------------------------------------------------------
# Hand-curated, in the well-known public style of ASCII-art collections
# shared across BBSes/forums/asciiart.eu for decades (bare line-art, no
# single canonical author, the same category crt-screensaver.py's FRAMES
# already draws from) -- NOT machine-scraped from a live URL at build or
# run time, since this project's offline-safe acceptance bar (see
# BOOK-GAME.md/FOCUS.md) means nothing here can depend on a fetch
# succeeding at the moment it's shown. Each entry is sized to fit inside
# the fallback 40x15 screen with room for a caption line below it.
ASCII_ART = {
    "book": r"""
     .-------.
    /  ___  / |
   /  /  / /  |
  /  /__/ /   |
 /_______/    |
 |       |    |
 |_______|___/
""",
    "cat_reading": r"""
   /\_/\
  ( o.o )   [BOOK]
   > ^ <   still reading...
""",
    "bookworm": r"""
   ____
  (o  o)~~ nom nom nom
   \  /
   /  \___
  (________)
""",
    "shelf": r"""
 |||  ||  ||||  |  ||||
 |||  ||  ||||  |  ||||
 =====================
""",
    # Kawaii/kaomoji entries (2026-07-21, registered in FOCUS.md), matching
    # the voice bin/crt-idle-bait.sh's existing "(=^-^=)" faces already
    # use elsewhere in this project -- hand-authored, same "not machine-
    # fetched" convention as the plain-line-art set above.
    "kawaii_cat": r"""
   (=^-w-^=)
   /|   book|\
    |________|
   still purring over this one~
""",
    "kawaii_owl": r"""
   (o=W=o)
    <")_(">
  librarian owl approves
""",
    "kawaii_sleepy": r"""
   (-.-)zzZ
    (")(")
  page-turner needs a nap
""",
}


def get_ascii_art(name):
    """Returns the named art, stripped of the leading/trailing blank line
    the triple-quoted literals above carry, or None for an unknown name --
    callers should treat a missing name as 'skip the art, not a hard
    failure' (the game round works fine without it)."""
    art = ASCII_ART.get(name)
    if art is None:
        return None
    return art.strip("\n")


# ---------------------------------------------------------------------------
# Idle-bait quotes: non-API, sourced from already-cached local data
# ---------------------------------------------------------------------------
# Deliberately NOT a Claude/API call -- per direction, this feature only
# ever reads what's already sitting in books.db (the raw Open Library
# response cached at scan time) or, failing that, a small static local
# fallback pool. No network, no live inference, at idle-bait time.
FALLBACK_QUOTES = [
    "a room without books is like a body without a soul.",
    "the person who deserves most pity is a lonesome one on a rainy day who doesn't know how to read.",
    "there is no friend as loyal as a book.",
    "once you learn to read, you will be forever free.",
    "books are a uniquely portable magic.",
]

# Enticement lines: distinct from the FALLBACK_QUOTES/scraped-quote path
# above -- those celebrate a book ALREADY scanned, these actively invite
# scanning a NEW one. This is the actual "idle-bait someone into picking
# up a book" mechanism (2026-07-21 direction: the whole point of this
# feature, not a side flourish) -- kaomoji voice matches
# bin/crt-idle-bait.sh's existing "(=^-^=)"-style lines, same character.
ENTICE_LINES = [
    "(・∀・)  got a book nearby? scan it, let's see what it is",
    "(=^-^=)  bored kitty here. bring a book, any book",
    "( closed book ) -> ( scanner ) -> ( trivia ). try it?",
    "\\(^o^)/  new book, new question -- scan one when you get a sec",
    "(o.o)  ...is that a book on the shelf? scan it and find out",
    "( ._.)  quiet in here. a barcode would liven things up",
]


def pick_entice_line(rng=None):
    """Pure function: picks a random enticement line inviting a NEW scan.
    Always non-empty (unlike pick_idle_quote, which needs a populated
    registry) -- this is the line shown when there's nothing to celebrate
    yet, or just to keep pulling for more scans alongside the quotes."""
    rng = rng or random
    return rng.choice(ENTICE_LINES)


def extract_quote(raw_book_data):
    """Pure function: pull a first-sentence-shaped quote out of an Open
    Library raw response if one exists (the ISBN endpoint doesn't always
    have it), else None -- callers fall back to FALLBACK_QUOTES rather
    than treating a missing quote as an error, since most scans won't
    have one."""
    fs = raw_book_data.get("first_sentence") if raw_book_data else None
    if isinstance(fs, dict):
        return fs.get("value")
    if isinstance(fs, str) and fs:
        return fs
    return None


WIKIQUOTE_SEARCH_URL = (
    "https://en.wikiquote.org/w/api.php?action=query&format=json"
    "&list=search&srlimit=5&srsearch={query}"
)
WIKIQUOTE_CONTENT_URL = (
    "https://en.wikiquote.org/w/api.php?action=query&format=json"
    "&prop=revisions&rvprop=content&rvslots=main&formatversion=2&titles={title}"
)
QUOTE_LINE_RE = re.compile(r"^\*(?!\*)\s*(.+)$", re.MULTILINE)
WIKI_LINK_RE = re.compile(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]")
WIKI_MARKUP_RE = re.compile(r"'{2,}")


def _clean_wikitext(text):
    text = WIKI_LINK_RE.sub(r"\1", text)
    text = WIKI_MARKUP_RE.sub("", text)
    return text.strip().strip('"').strip()


def _truncate_quote(text, max_len=180):
    if len(text) <= max_len:
        return text
    truncated = text[:max_len]
    last_period = truncated.rfind(". ")
    if last_period > 40:
        return truncated[: last_period + 1]
    return truncated.rstrip() + "..."


def _wikiquote_search(query, fetcher):
    data = fetcher(WIKIQUOTE_SEARCH_URL.format(query=urllib.parse.quote(query)))
    return [r["title"] for r in data.get("query", {}).get("search", [])]


def _wikiquote_page_content(title, fetcher):
    data = fetcher(WIKIQUOTE_CONTENT_URL.format(title=urllib.parse.quote(title)))
    pages = data.get("query", {}).get("pages", [])
    if not pages:
        return None
    revisions = pages[0].get("revisions")
    if not revisions:
        return None
    return revisions[0]["slots"]["main"]["content"]


def extract_quote_candidates(wikitext):
    """Pure function: pulls real quote lines out of Wikiquote wikitext.
    Top-level '* text' lines are quotes; '** text' lines (note the
    negative lookahead below) are attributions/sources, skipped. Strips
    [[wiki|links]] and '''bold'''/''italic'' markup. Filters out anything
    under 20 chars (section-header debris, stray fragments) -- best
    effort, not a real wikitext parser."""
    candidates = []
    for m in QUOTE_LINE_RE.finditer(wikitext or ""):
        line = _clean_wikitext(m.group(1))
        if len(line) >= 20 and not line.startswith("{{") and not line.startswith("[[File"):
            candidates.append(line)
    return candidates


def scrape_quote(title, fetcher=None, rng=None):
    """Best-effort: search Wikiquote for `title`, pull one real quote line
    from the page's own wikitext. NOT an AI call -- this is literal text
    scraped from Wikiquote's CC BY-SA content, not a paraphrase. Returns
    None on ANY failure (no page found, no quotes parsed, network error/
    timeout) so callers always have a graceful fallback -- see
    BOOK-GAME-STYLE.md's idle-bait fallback chain. `fetcher` is injectable
    for tests (callable(url) -> parsed JSON dict), same pattern as
    fetch_book_metadata."""
    fetcher = fetcher or _http_get_json
    rng = rng or random
    try:
        results = _wikiquote_search(title, fetcher)
        if not results:
            return None
        wikitext = _wikiquote_page_content(results[0], fetcher)
        candidates = extract_quote_candidates(wikitext)
        if not candidates:
            return None
        return _truncate_quote(rng.choice(candidates))
    except Exception:
        return None


def pick_idle_quote(conn, rng=None):
    """Picks one registered book at random and returns (title, quote) for
    an idle-bait line. Fallback chain, in priority order: (1) a quote
    scraped once at registration time and cached in the `quote` column,
    (2) that book's own cached Open Library first_sentence, (3) a
    deterministic (isbn-seeded, stable across calls for the same book)
    pick from FALLBACK_QUOTES. Returns None if the registry is empty."""
    rng = rng or random
    rows = conn.execute("SELECT isbn, title, quote, raw_json FROM books").fetchall()
    if not rows:
        return None
    isbn, title, quote, raw_json = rng.choice(rows)
    if not quote:
        quote = extract_quote(json.loads(raw_json or "{}"))
    if not quote:
        idx = int(hashlib.sha256(isbn.encode()).hexdigest(), 16) % len(FALLBACK_QUOTES)
        quote = FALLBACK_QUOTES[idx]
    return title, quote


# ---------------------------------------------------------------------------
# Scanner-feed integration: bridges bin/crt-scanner-feed.py's delivery
# convention (SCANNER.md) with this CLI's plain --isbn argument
# ---------------------------------------------------------------------------

SCAN_PREFIX = "[scan] "
ISBN_RE = re.compile(r"\d{9}[\dXx]|\d{13}")


def is_isbn_like(text):
    """Pure function: does `text` look like a bare ISBN-10/13 (optional
    trailing check-digit 'X')? Shared by parse_scan_line (tmux-delivered,
    prefixed) and crt-book-console.py (tails ~/.crt/scanner.log directly,
    unprefixed) so the two entry points can't drift on what counts as a
    valid scan."""
    return bool(re.fullmatch(ISBN_RE, text.strip()))


def parse_scan_line(line):
    """Pure function: strips crt-scanner-feed.py's '[scan] ' delivery
    prefix (SCANNER.md) and returns the bare ISBN, or None if the line
    isn't a scan line or doesn't look like an ISBN. Kept here rather than
    in crt-scanner-feed.py itself since that script is a generic deliver-
    anything-into-tmux listener and shouldn't need to know book-game
    specifics -- the hands-on wiring step (BOOK-GAME.md roadmap step 3)
    is expected to call this before shelling out to --isbn."""
    line = line.strip()
    if not line.startswith(SCAN_PREFIX):
        return None
    candidate = line[len(SCAN_PREFIX):].strip()
    return candidate.upper() if is_isbn_like(candidate) else None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Book Game (offline-safe slice)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--isbn", help="bare ISBN")
    group.add_argument("--scan-line", help="a raw line as delivered by crt-scanner-feed.py, e.g. '[scan] 9780141439518'")
    parser.add_argument("--answer", help="spoken/typed answer to grade against a pending question")
    args = parser.parse_args()

    isbn = args.isbn
    if args.scan_line:
        isbn = parse_scan_line(args.scan_line)
        if isbn is None:
            print(f"Not a recognizable scan line/ISBN: {args.scan_line!r}")
            return

    conn = get_db()
    existing = get_book(conn, isbn)
    if existing is None:
        try:
            book = fetch_book_metadata(isbn)
        except Exception as e:
            # Confirmed live: Open Library 404s on any ISBN it doesn't
            # recognize, and this is the EXPECTED outcome for a real
            # fraction of scans (out-of-print books, non-ISBN products,
            # a network hiccup) -- not a hypothetical edge case, so this
            # CLI must degrade to a clear message, never a raw traceback.
            print(f"Couldn't look up ISBN {isbn}: {e}")
            return
        source = pick_question_source()
        # Live Claude-batch calls need a real crt-vm session (see
        # BOOK-GAME.md); this standalone CLI always uses the template
        # path so a fresh scan never blocks on network/API access, but
        # still records which source *would* have been used.
        question = generate_template_question(book)
        quote = scrape_quote(book["title"])
        row = register_book(conn, book, questions=[question], question_source=source, quote=quote)
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
        log_training_row(isbn, grade)
        print(f"correct_content={grade['correct_content']} correct_stt={grade['correct_stt']}")


if __name__ == "__main__":
    main()
