#!/usr/bin/env python3
# Closes the last open link in the Book Game funnel (idle-bait -> scan ->
# question -> SPOKEN ANSWER -> STT training log, see .claude/FOCUS.md's
# 2026-07-21 end-goal statement): watches ~/.crt/stt.log (already written
# by crt-stt-solo.py for every recognized utterance, whether or not it's
# addressed to Claude) for the next utterance after a scan and grades it
# against that scan's pending question -- see tests/test_book_answer_listen.py.
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
    time), else None -- entirely derived from books.db's own timestamps,
    never a separate 'pending' flag/state to drift out of sync.

    Four claims, each with its own witness rather than restated here:
    - ORDER BY last_scanned, not first_scanned, so a rescan is seen:
      tests/test_book_rescan_pending.py::TestRescannedBookIsPending
    - COALESCE covers rows predating that column:
      tests/test_book_rescan_pending.py::TestTouchScan
      ::test_a_row_predating_the_column_still_answers_for_its_first_scan
    - a round CLOSES once graded, and a rescan reopens it:
      tests/test_book_answer_round_closes.py::TestOneScanIsOneRound
      ::TestRescanReopensTheRound
    - the answered check runs after LIMIT 1, not as a WHERE clause, so a
      closed round can't fall through to the previous book:
      tests/test_book_answer_round_closes.py
      ::TestClosedRoundDoesNotFallThroughToAnotherBook"""
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
    # >= not >: see test_a_same_second_answer_still_closes_the_round.
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

    Three checks below, each closing a door where an utterance addressed
    elsewhere got graded as the trivia answer instead of left alone --
    each one's incident is told in full on its own test file, not
    repeated here:

    - A voice COMMAND ("book game stats", "back to the book game") is not
      an answer attempt. Reuses crt-secretary.py's own find_playbook() so
      this can never drift out of sync with what counts as a command
      elsewhere in the project. See tests/test_book_answer_listen.py.
    - A WAKE WORD ("claude, what is this book about?") is a request to
      Claude, not an answer attempt -- asked through bin/crt_wake_gate.py,
      the same anti-drift move as the command check above. Checked BEFORE
      the pending-question lookup: whether this was addressed to the
      console has nothing to do with whether a book is open. See
      tests/test_book_answer_wake_word.py.
    - An ARM-WINDOW follow-up (CRT_WAKE_ARM_ENABLED) reaches Claude
      WITHOUT the wake word by design (bin/crt-wake-arm.py), so the wake
      check above can't catch it -- same anti-drift move again, and a
      no-op whenever arming is off since nothing ever publishes a window
      then. See tests/test_book_answer_arm_window.py.

    What this does NOT decide: whether an arm-window follow-up SHOULD be
    able to answer the question on the tube instead of going to Claude.
    Today it goes to Claude -- the engine has already routed it by the time
    this runs -- and grading it here as well is double-handling, not a
    second opinion. Open for Zach in vault:crt/BATCH-NOTES.md."""
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
    # options= matters as much as the other two -- see bg.grade_answer's
    # own docstring for why.
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
    # errors="replace": raised here, in the generator, a UnicodeDecodeError
    # is outside main()'s LoopGuard. Witnessed by
    # tests/test_log_reader_decoding.py::test_book_answer_listen_tail_does_not_raise.
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
    # of the console's uptime -- see crt_loop_guard.py's LoopGuard docstring.
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
