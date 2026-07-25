#!/usr/bin/env python3
# Closes the last open link in the Book Game funnel (idle-bait -> scan ->
# question -> SPOKEN ANSWER -> STT training log, see .claude/FOCUS.md's
# 2026-07-21 end-goal statement): watches ~/.crt/stt.log (already written
# by crt-stt-solo.py for every recognized utterance, whether or not it's
# addressed to Claude) for the next utterance after a scan, and grades it
# against that scan's pending question automatically -- no more manual
# `crt-book-game.py --answer` required for the common case.
#
# NOT a new Claude/API call, NOT a new STT engine -- purely reads a log
# that already exists and reuses crt-book-game.py's existing
# grade_answer()/log_training_row() functions. Deliberately its own file
# rather than an edit to crt-book-console.py or crt-book-game.py, since
# both are mid-live-debug elsewhere as of 2026-07-21 (missing `random`
# import, quote-column migration) -- avoids colliding with that work.
#
# "Pending question" is derived, not stored as new shared state: the
# most recently SCANNED book (MAX of last_scanned, falling back to
# first_scanned) counts as pending only while
# CRT_BOOK_ANSWER_WINDOW_SECS hasn't elapsed since that scan -- after
# that, the next STT utterance is assumed to be unrelated chatter, not a
# trivia answer, and is left alone (not graded, not consumed). Until
# 2026-07-25 this read first_scanned alone, which meant a book could only
# ever be answered the very first time it was scanned.
#
# STATUS: NOT hardware-verified. Timestamp math and the tail-follow/grade
# logic are pure functions covered by tests/test_book_answer_listen.py
# against a fixture books.db + stt.log; never run against a real scan +
# real spoken answer.
#
# Usage: crt-book-answer-listen.py   (run as its own tmux window/background loop)
# Env:
#   CRT_BOOKS_DB (default ~/.crt/books.db, same as crt-book-game.py)
#   CRT_STT_LOG (default ~/.crt/stt.log, same as crt-stt-solo.py)
#   CRT_THOUGHT_LOG (default ~/.crt/thoughts.log) -- where the graded
#     result announcement is appended (crt-monologue.sh already tails
#     this and shows it on screen, same channel crt-book-idle-bait.py
#     and crt-idle-teaser.sh already write to)
#   CRT_BOOK_ANSWER_WINDOW_SECS (default 20) -- how long after a scan an
#     utterance still counts as "the answer to that question"
import calendar
import importlib.util
import json
import os
import time

BIN_DIR = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("crt_book_game", os.path.join(BIN_DIR, "crt-book-game.py"))
bg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bg)

_secretary_spec = importlib.util.spec_from_file_location(
    "crt_secretary_for_book_answer", os.path.join(BIN_DIR, "crt-secretary.py"))
secretary = importlib.util.module_from_spec(_secretary_spec)
_secretary_spec.loader.exec_module(secretary)

# Loaded the same way as the two above rather than by plain `import`: this
# file is itself loaded by spec_from_file_location from tests, which does
# not put BIN_DIR on sys.path.
_guard_spec = importlib.util.spec_from_file_location(
    "crt_loop_guard_for_book_answer", os.path.join(BIN_DIR, "crt_loop_guard.py"))
loop_guard = importlib.util.module_from_spec(_guard_spec)
_guard_spec.loader.exec_module(loop_guard)

STT_LOG = os.path.expanduser(os.environ.get("CRT_STT_LOG", "~/.crt/stt.log"))
THOUGHT_LOG = os.path.expanduser(os.environ.get("CRT_THOUGHT_LOG", "~/.crt/thoughts.log"))
ANSWER_WINDOW_SECS = float(os.environ.get("CRT_BOOK_ANSWER_WINDOW_SECS", "20"))
POLL_SECS = float(os.environ.get("CRT_BOOK_ANSWER_LISTEN_POLL_SECS", "0.5"))


def parse_stt_log_line(line):
    """Pure function: crt-stt-solo.py writes 'HH:MM:SS  text' (two
    spaces, no date -- see its STT_LOG write). Returns the bare
    transcribed text, or None if the line doesn't have that shape.
    Freshness is judged by wall-clock time this line is SEEN, not by
    parsing this timestamp (which has no date and can't be compared
    against a scan's ISO timestamp directly)."""
    line = line.rstrip("\n")
    parts = line.split("  ", 1)
    if len(parts) != 2:
        return None
    ts, text = parts
    if len(ts) != 8 or ts.count(":") != 2:
        return None
    return text.strip() or None


def get_pending_question(conn, window_secs, now=None):
    """Returns {"isbn", "title", "question"} for the most recently SCANNED
    book if that scan was within `window_secs` of `now` (default: real
    time), else None -- no separate 'pending' flag/state needed, this is
    entirely derived from books.db's own timestamps, so it can never drift
    out of sync with what actually got scanned.

    Ordered by last_scanned, not first_scanned (2026-07-25): re-scanning a
    book already on the shelf leaves first_scanned exactly where it was --
    register_book() caches, deliberately -- so this used to see no scan at
    all and drop the spoken answer, or worse, pick some *other* book that
    happened to be registered inside the window and grade the answer
    against ITS question, writing a training row whose "expected" belongs
    to a different book. That is a corrupted row in the file this whole
    console exists to fill.

    COALESCE, not a backfill: rows written before that column existed have
    last_scanned NULL and still answer for their first scan.

    A round is also CLOSED once it has been graded (2026-07-25, thirteenth
    cycle): last_answered at or after this book's own scan means the answer
    already happened, so the next utterance is not a second attempt at the
    same question. It is compared against the SCAN, not against the clock,
    so re-scanning the book re-opens the round without anything having to
    clear the column.

    The answered check deliberately happens AFTER `LIMIT 1`, not as a WHERE
    clause. Filtering in SQL would make a closed round fall through to the
    second-most-recently-scanned book, which may still be inside its own
    window -- and grading an utterance against a book that is not the one
    on the tube is exactly the corrupted training row the twelfth cycle
    fixed. The most recent scan is the question on screen; if that one is
    closed, nothing is pending."""
    now = now if now is not None else time.time()
    row = conn.execute(
        "SELECT isbn, title, questions_json, "
        "COALESCE(last_scanned, first_scanned) AS scanned, last_answered "
        "FROM books ORDER BY scanned DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    isbn, title, questions_json, scanned, last_answered = row
    scanned_at = _parse_iso_utc(scanned)
    if scanned_at is None or now - scanned_at > window_secs:
        return None
    answered_at = _parse_iso_utc(last_answered)
    # >= not >: _now_iso() has one-second resolution, so an answer graded in
    # the same second as the scan that opened it is indistinguishable from
    # one graded just before it. Treating equal as closed errs toward
    # silence for a sub-second re-scan; treating it as open would reopen
    # this whole bug for anyone who answers quickly.
    if answered_at is not None and answered_at >= scanned_at:
        return None
    questions = json.loads(questions_json or "[]")
    if not questions:
        return None
    return {"isbn": isbn, "title": title, "question": questions[0]}


def _parse_iso_utc(ts):
    """Pure function: parses crt-book-game.py's _now_iso() format
    ('%Y-%m-%dT%H:%M:%S', always gmtime/UTC) into a Unix epoch float, or
    None if it doesn't parse -- a malformed/missing timestamp should mean
    'not pending', never a crash. calendar.timegm (not time.mktime) since
    the struct_time IS already UTC -- mktime would apply the local
    timezone/DST offset on top, which is wrong here."""
    if not ts:
        return None
    try:
        return calendar.timegm(time.strptime(ts, "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return None


def _iso_utc(epoch):
    """Inverse of _parse_iso_utc: crt-book-game.py's _now_iso() format from
    a Unix epoch. Exists so that a caller passing an explicit `now` closes
    the round at THAT instant rather than at the wall clock -- otherwise
    the two halves of one graded round disagree about when it happened."""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(epoch))


def grade_pending_answer(conn, spoken_text, window_secs=ANSWER_WINDOW_SECS, now=None):
    """The whole close-the-loop step: if there's a pending question, grade
    `spoken_text` against it and log the training row (reusing
    crt-book-game.py's own grade_answer/log_training_row -- no new
    grading logic). Returns the grade dict (plus the book's title, for
    format_result_line() below) or None if nothing was pending (caller
    should leave the utterance alone -- it wasn't a trivia answer).

    HAPPY-PATH BUG FIXED 2026-07-21: previously graded ANY utterance
    inside the answer window as the trivia answer, with no check for
    whether it was actually a voice COMMAND instead -- e.g. asking "book
    game stats" or "back to the book game" within CRT_BOOK_ANSWER_WINDOW_SECS
    of a scan (a completely ordinary thing to say right after scanning,
    before answering) would get logged as a wrong/garbage training row
    ("expected": "fiction", "heard": "book game stats") AND announced as
    a misleading "nope, it was fiction" result for a question the user
    never actually tried to answer. Now skips grading (returns None,
    same as "nothing pending") for any utterance crt-secretary.py's own
    playbook dispatcher would recognize as a command -- reuses
    find_playbook() so this can never drift out of sync with what
    actually counts as a command elsewhere in the project."""
    if secretary.find_playbook(spoken_text)[0] is not None:
        return None
    pending = get_pending_question(conn, window_secs, now=now)
    if pending is None:
        return None
    q = pending["question"]
    grade = bg.grade_answer(expected=q.get("correct"), heard=spoken_text, correct_option=q.get("correct"))
    # Close the round BEFORE logging it. If this UPDATE fails, the round
    # stays open and the very next thing anyone says gets graded against
    # the same question -- so failing here must not leave a training row
    # already written behind it. books.db is WAL with a 10s busy timeout
    # (get_db), so contention is not the realistic failure; a raise here
    # reaches main()'s LoopGuard and is reported on window 1 rather than
    # silently double-grading.
    bg.mark_answered(conn, pending["isbn"],
                     timestamp=None if now is None else _iso_utc(now))
    bg.log_training_row(pending["isbn"], grade)
    grade["title"] = pending["title"]
    return grade


def format_result_line(grade):
    """Pure function: the actual game-show-host announcement, in the
    register BOOK-GAME-STYLE.md's personality section calls for --
    content/settled ('got it') for a right answer, clipped ('nope, it
    was X') for wrong, never gloating or sad-trombone either way (this
    is a game, wrong answers are half the fun). `correct_content is None`
    (an ungradeable fallback question, e.g. 'have you read this before')
    gets a neutral acknowledgment instead of a right/wrong verdict --
    there was nothing to grade.

    A correct answer also appends the `bookworm` ASCII art --
    BOOK-GAME-STYLE.md named this exact pairing ("bookworm on a correct
    answer") back when the art library was built, but it was never
    actually wired in anywhere until now (only `shelf` was, in the idle
    screen). Embedded as literal newlines in the returned string:
    thoughts.log's own tail-by-line reader (crt-monologue.py) treats
    each physical line as its own independently-faded entry regardless,
    so a multi-line block here just becomes a few closely-timed lines in
    the scrollback -- no special handling needed downstream."""
    if grade["correct_content"] is None:
        return bg.wrap_color(f"  logged your answer for {grade['title']}.", bg.COLOR_QUESTION)
    if grade["correct_content"]:
        text = f"  got it! {grade['title']}: {grade['expected']}."
        art = bg.get_ascii_art("bookworm") or ""
        if art:
            text += "\n" + art
        return bg.wrap_color(text, bg.COLOR_CORRECT)
    return bg.wrap_color(f"  nope, it was {grade['expected']} -- {grade['title']}.", bg.COLOR_WRONG)


def tail_new_lines(path):
    """Same shape as crt-book-console.py's tail_new_lines (kept as its
    own copy here, not a shared import, to avoid any coupling with a file
    under active live debugging elsewhere) -- yields new lines as they
    arrive, or None on an empty poll so the caller can still tick."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a"):
        pass
    # errors="replace": a readline() racing crt-stt-solo.py's appends can
    # land inside a multi-byte character. UnicodeDecodeError raised HERE,
    # in the generator, is outside main()'s LoopGuard (which wraps the body
    # only) -- so strict decoding is one of the few remaining ways this
    # window can still die outright.
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        f.seek(0, os.SEEK_END)
        while True:
            line = f.readline()
            if line:
                yield line
            else:
                time.sleep(POLL_SECS)
                yield None


def announce(line):
    """Appends the formatted result line to thoughts.log (best-effort --
    a broken log write must never crash grading, same convention as
    crt-secretary.py's log_fallthrough)."""
    try:
        os.makedirs(os.path.dirname(THOUGHT_LOG), exist_ok=True)
        with open(THOUGHT_LOG, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def main():
    conn = bg.get_db()
    # This is the LAST link of the Book Game funnel and a stability-bar
    # item. Before 2026-07-25 one raising utterance ended it for the rest
    # of the console's uptime: grade_pending_answer() reaches sqlite (a
    # locked or corrupt books.db), json.loads (a malformed questions_json
    # row), and log_training_row's own write. Any of those took the whole
    # window down silently, and the only symptom was that answering a
    # trivia question stopped doing anything ever again.
    #
    # Guarding the body, not the tail: new lines only arrive as fast as
    # someone speaks, so a body that fails every time cannot spin.
    guard = loop_guard.LoopGuard("bookanswer")
    for line in tail_new_lines(STT_LOG):
        if line is None:
            continue
        with guard:
            text = parse_stt_log_line(line)
            if text is None:
                continue
            grade = grade_pending_answer(conn, text)
            if grade is not None:
                print(f"[book-answer] heard={grade['heard']!r} "
                      f"correct_content={grade['correct_content']} correct_stt={grade['correct_stt']}")
                announce(format_result_line(grade))


if __name__ == "__main__":
    main()
