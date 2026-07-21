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
# most recently *registered* book (MAX(first_scanned)) counts as pending
# only while CRT_BOOK_ANSWER_WINDOW_SECS hasn't elapsed since its scan --
# after that, the next STT utterance is assumed to be unrelated chatter,
# not a trivia answer, and is left alone (not graded, not consumed).
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

STT_LOG = os.path.expanduser(os.environ.get("CRT_STT_LOG", "~/.crt/stt.log"))
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
    """Returns {"isbn", "title", "question"} for the most recently
    registered book if it was scanned within `window_secs` of `now`
    (default: real time), else None -- no separate 'pending' flag/state
    needed, this is entirely derived from books.db's own first_scanned
    column, so it can never drift out of sync with what actually got
    registered."""
    now = now if now is not None else time.time()
    row = conn.execute(
        "SELECT isbn, title, questions_json, first_scanned FROM books "
        "ORDER BY first_scanned DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    isbn, title, questions_json, first_scanned = row
    scanned_at = _parse_iso_utc(first_scanned)
    if scanned_at is None or now - scanned_at > window_secs:
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


def grade_pending_answer(conn, spoken_text, window_secs=ANSWER_WINDOW_SECS, now=None):
    """The whole close-the-loop step: if there's a pending question, grade
    `spoken_text` against it and log the training row (reusing
    crt-book-game.py's own grade_answer/log_training_row -- no new
    grading logic). Returns the grade dict, or None if nothing was
    pending (caller should leave the utterance alone -- it wasn't a
    trivia answer)."""
    pending = get_pending_question(conn, window_secs, now=now)
    if pending is None:
        return None
    q = pending["question"]
    grade = bg.grade_answer(expected=q.get("correct"), heard=spoken_text, correct_option=q.get("correct"))
    bg.log_training_row(pending["isbn"], grade)
    return grade


def tail_new_lines(path):
    """Same shape as crt-book-console.py's tail_new_lines (kept as its
    own copy here, not a shared import, to avoid any coupling with a file
    under active live debugging elsewhere) -- yields new lines as they
    arrive, or None on an empty poll so the caller can still tick."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a"):
        pass
    with open(path, "r") as f:
        f.seek(0, os.SEEK_END)
        while True:
            line = f.readline()
            if line:
                yield line
            else:
                time.sleep(POLL_SECS)
                yield None


def main():
    conn = bg.get_db()
    for line in tail_new_lines(STT_LOG):
        if line is None:
            continue
        text = parse_stt_log_line(line)
        if text is None:
            continue
        grade = grade_pending_answer(conn, text)
        if grade is not None:
            print(f"[book-answer] heard={grade['heard']!r} "
                  f"correct_content={grade['correct_content']} correct_stt={grade['correct_stt']}")


if __name__ == "__main__":
    main()
