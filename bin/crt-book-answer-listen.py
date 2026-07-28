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
#   CRT_BOOK_ANSWER_WINDOW_SECS (default 35, was 20 -- 2026-07-28,
#     Zach-directed: "need more of a delay between question and answer",
#     kept in step with crt-book-console.py's IDLE_SECS so the question
#     doesn't leave the screen before an answer would still be graded)
#     -- how long after a scan an utterance still counts as "the answer
#     to that question"
#   CRT_WAKE_WORD (default claude) and CRT_STT_FIXUPS -- read only to
#     recognize an utterance addressed to the console and leave it alone;
#     both resolved exactly as crt-stt-solo.py's gate resolves them, via
#     bin/crt_wake_gate.py. crt-console.sh hands every window one
#     environment, so the two cannot disagree unless someone sets one of
#     them for a single tmux window.
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

# The wake gate's own question, not a second opinion about it -- see
# bin/crt_wake_gate.py's header. Deliberately NOT an import of
# crt-stt-solo.py: that module runs `arecord -l` at import time and pulls in
# the whole capture engine, neither of which belongs in this window.
_wg_spec = importlib.util.spec_from_file_location(
    "crt_wake_gate_for_book_answer", os.path.join(BIN_DIR, "crt_wake_gate.py"))
wake_gate = importlib.util.module_from_spec(_wg_spec)
_wg_spec.loader.exec_module(wake_gate)

# The OTHER way an utterance reaches Claude without carrying the wake word
# (2026-07-25, twentieth cycle): the sticky-conversation window. Loaded for
# arm_window_open() alone -- this window never runs the state machine, it
# only asks whether the engine has one open. Light: os/re/subprocess/time.
_arm_spec = importlib.util.spec_from_file_location(
    "crt_wake_arm_for_book_answer", os.path.join(BIN_DIR, "crt-wake-arm.py"))
wake_arm = importlib.util.module_from_spec(_arm_spec)
_arm_spec.loader.exec_module(wake_arm)

STT_LOG = os.path.expanduser(os.environ.get("CRT_STT_LOG", "~/.crt/stt.log"))
THOUGHT_LOG = os.path.expanduser(os.environ.get("CRT_THOUGHT_LOG", "~/.crt/thoughts.log"))
ANSWER_WINDOW_SECS = float(os.environ.get("CRT_BOOK_ANSWER_WINDOW_SECS", "35"))
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
    actually counts as a command elsewhere in the project.

    THE SAME SHAPE, THE OTHER HALF, FIXED 2026-07-25 (fourteenth cycle): an
    utterance carrying the WAKE WORD is a request to Claude, and was being
    graded as a trivia answer for exactly the same reason commands were.
    "claude, what is this book about?" is an ordinary thing to say to a
    console that has just put a question on the tube, and it is not a
    command -- no playbook matches it, it falls through to Claude. So the
    tube announced "nope, it was fiction", a row went into
    book-game-training.jsonl whose `heard` was never an answer attempt, and
    once the round started closing on the first graded utterance (2776f99)
    the person's real answer a second later was silently not graded at all.
    Asked through bin/crt_wake_gate.py, which is the gate's own rule
    including its learned aliases -- the same anti-drift move find_playbook()
    is above. Checked BEFORE the pending-question lookup: whether this was
    addressed to the console has nothing to do with whether a book is open.

    THE THIRD DOOR, CLOSED 2026-07-25 (twentieth cycle): an arm-window
    follow-up. Once CRT_WAKE_ARM_ENABLED is on -- and the stability
    milestone's first bar item is exactly that, live -- a wake opens a
    sticky-conversation window, and the utterances inside it reach Claude
    WITHOUT the wake word, by design (bin/crt-wake-arm.py; the live
    2026-07-23 bug was four follow-ups in one breath all gate-dropped). So
    the funnel's own scenario replays with the wake word one utterance
    earlier and every check above passes:

        scan -> tube shows "Fiction or nonfiction?"
             -> "claude, are you there?"        (wake: skipped here, arms)
             -> "what is this book about?"      (follow-up: routed to Claude)
             -> tube: "nope, it was fiction"
             -> a row whose `heard` was never an answer attempt
             -> "fiction" -- NOT graded, the round closed on the row above

    That is the fourteenth cycle's defect exactly, through a door that
    opens when the milestone's OTHER bar item goes live. Asked of
    crt-wake-arm.py, which is the window's own rule, the same anti-drift
    move find_playbook() and the wake gate are above -- and a no-op
    whenever arming is off, since nothing ever publishes a window then.

    What this does NOT decide: whether an arm-window follow-up SHOULD be
    able to answer the question on the tube instead of going to Claude.
    Today it goes to Claude -- the engine has already routed it by the time
    this runs -- and grading it here as well is double-handling, not a
    second opinion. Open for Zach in BATCH-NOTES.md."""
    if secretary.find_playbook(spoken_text)[0] is not None:
        return None
    if wake_gate.addressed_to_console(spoken_text):
        return None
    if wake_arm.arm_window_open(now=now):
        return None
    pending = get_pending_question(conn, window_secs, now=now)
    if pending is None:
        return None
    q = pending["question"]
    # options= matters as much as the other two (2026-07-25): without it
    # correct_stt collapses into correct_content and an honest wrong answer
    # gets logged as a mishear. See bg.grade_answer's own docstring.
    grade = bg.grade_answer(expected=q.get("correct"), heard=spoken_text,
                            correct_option=q.get("correct"), options=q.get("options"))
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
