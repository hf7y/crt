#!/usr/bin/env python3
# The "growing string of wake words" (2026-07-21, Zach's direct ask):
# instead of a single fixed wake word ("claude"), ungated utterances are
# checked against a POOL of candidate wake words that grows over time --
# some hand-seeded (CRT_WAKE_POOL_DICT, a plain one-per-line word list),
#   [rest: vault:crt/header-archaeology-20260817.md]
import difflib
import importlib.util
import os
import re

BIN_DIR = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("crt_book_game", os.path.join(BIN_DIR, "crt-book-game.py"))
_bg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_bg)

DICT_PATH = os.path.expanduser(os.environ.get("CRT_WAKE_POOL_DICT", "~/.crt/wake-pool-dict.txt"))
MAX_BOOK_TITLES = int(os.environ.get("CRT_WAKE_POOL_MAX_BOOK_TITLES", "200"))


def load_dict_words(path=None):
    """Tolerant read: missing/malformed file yields an empty set, never a
    crash -- the pool degrades to book-title words only, not a failure."""
    path = path or DICT_PATH
    words = set()
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                words.add(line.lower())
    except OSError:
        pass
    return words


def title_words(title):
    """The significant (4+ letter) words of a book title, lowercased --
    short filler words ("the", "of", "a") would false-positive constantly
    as ambient speech, so they're excluded from the pool entirely."""
    return {w for w in re.findall(r"[a-z0-9']+", title.lower()) if len(w) >= 4}


def load_book_title_words(conn, max_titles=None):
    """Pure-ish (only reads conn): every significant word from the most
    recently scanned books' titles, capped at max_titles books."""
    max_titles = max_titles if max_titles is not None else MAX_BOOK_TITLES
    rows = conn.execute(
        "SELECT title FROM books ORDER BY first_scanned DESC LIMIT ?", (max_titles,)
    ).fetchall()
    words = set()
    for (title,) in rows:
        if title:
            words |= title_words(title)
    return words


def load_pool(dict_path=None, db_conn=None):
    """The full current wake pool: hand-seeded dict words union book-title
    words. db_conn is optional (None skips the book-title half entirely --
    e.g. no books.db yet, or a caller that only wants the dict)."""
    pool = load_dict_words(dict_path)
    if db_conn is not None:
        pool |= load_book_title_words(db_conn)
    return pool


def check_pool_match(text, pool):
    """True if any whole word in `text` exactly matches a pool entry.
    Whole-word only (same reasoning as addressed_to_console): a bare
    substring match would false-positive on unrelated words."""
    words = re.findall(r"[a-z0-9']+", text.lower())
    return any(w in pool for w in words)


# Fuzzy cluster matching (2026-07-21, Zach's direct ask, calibration-game
# pass): "a longer set of words requiring less precision on one word but
# more reliable matching across words -- many close matches means it's
# probably the same." Rather than requiring one word to match a pool
#   [rest: vault:crt/header-archaeology-20260817.md]
FUZZY_CLOSE_RATIO = float(os.environ.get("CRT_WAKE_FUZZY_CLOSE_RATIO", "0.72"))
FUZZY_CLUSTER_MIN = int(os.environ.get("CRT_WAKE_FUZZY_CLUSTER_MIN", "2"))


def closest_pool_word(word, pool):
    """Pure function: the single pool word `word` is most similar to, and
    its similarity ratio (difflib.SequenceMatcher, stdlib, no new
    dependency) -- (None, 0.0) if the pool is empty. Not filtered by
    FUZZY_CLOSE_RATIO itself; callers decide what counts as "close"."""
    best_word, best_ratio = None, 0.0
    for candidate in pool:
        ratio = difflib.SequenceMatcher(None, word, candidate).ratio()
        if ratio > best_ratio:
            best_word, best_ratio = candidate, ratio
    return best_word, best_ratio


def fuzzy_cluster_match(text, pool, close_ratio=None, cluster_min=None):
    """True if at least `cluster_min` DISTINCT words in `text` are each
    individually within `close_ratio` similarity of some pool word (an
    exact match counts as maximally close, so this is a strict superset
    of check_pool_match -- a single perfect hit still passes if
    cluster_min is 1, but the real point is accepting several imperfect
    hits none of which alone would clear a stricter single-word bar).
    Words shorter than 4 letters are skipped (same filter title_words()
    already applies) -- short words have too many accidental near-matches
    to be useful signal (e.g. "and"/"end"/"ant" are all "close" to nearly
    anything short)."""
    close_ratio = close_ratio if close_ratio is not None else FUZZY_CLOSE_RATIO
    cluster_min = cluster_min if cluster_min is not None else FUZZY_CLUSTER_MIN
    if not pool:
        return False
    words = [w for w in re.findall(r"[a-z0-9']+", text.lower()) if len(w) >= 4]
    close_count = 0
    for w in words:
        _, ratio = closest_pool_word(w, pool)
        if ratio >= close_ratio:
            close_count += 1
    return close_count >= cluster_min


def pick_suggestion(pool, index=0, exclude=None):
    """One pool word to show as a 'did you mean to say...' suggestion.
    Deterministic given (pool, index) rather than random, so it's
    testable/reproducible, but ROTATES across successive calls via
    `index` (callers pass an incrementing counter, e.g.
    crt-stt-solo.py's gate-drop count) -- otherwise every suggestion
    would be the same alphabetically-first word forever, defeating the
    point of a growing, varied pool. Returns None if the pool is empty
    (nothing to suggest)."""
    candidates = sorted(pool - (exclude or set()))
    return candidates[index % len(candidates)] if candidates else None


if __name__ == "__main__":
    conn = _bg.get_db()
    pool = load_pool(db_conn=conn)
    print(f"{len(pool)} candidate wake word(s) in the pool.")
    for w in sorted(pool):
        print(" ", w)
