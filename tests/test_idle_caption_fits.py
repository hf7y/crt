#!/usr/bin/env python3
"""The line that asks for a book fits on the tube, and still asks.

WHY THIS EXISTS (2026-07-25, seventeenth nightly cycle). Two faults in the
same statement -- `_place_text(caption[:bg.MAX_CONTENT_WIDTH], width, align)`.

**It counted characters.** MAX_CONTENT_WIDTH is Zach's 2026-07-21 hard rule
and the tube is 40 columns, but the enticement lines are kaomoji and
U+30FB KATAKANA MIDDLE DOT is East Asian Wide. Rendered from the real
function, before this cycle:

    chars=30 cols=32  '(・∀・)  got a book nearby? scan'

Thirty characters, thirty-two columns, padded as if it were thirty -- so the
line was drawn 42 columns wide into a 40-column pane and wrapped. The same
arithmetic sits under every book title this console draws, and Open Library
will hand back a CJK or fullwidth title for a perfectly ordinary scan.

**It cut where the budget ran out.** All six enticement lines are longer
than 30 columns, so all six lost their ending, and four lost the ask itself:

    '( closed book ) -> ( scanner )'        <- '-> ( trivia ). try it?' gone
    '\\(^o^)/  new book, new questio'        <- '-- scan one ...' gone
    '(o.o)  ...is that a book on th'        <- 'scan it and find out' gone
    '(・∀・)  got a book nearby? scan'       <- 'scan it, ...' gone

The screen whose whole job is to talk someone into scanning a book had
stopped saying so, in four cases out of six, and said nothing about having
been cut -- the same dangling-fragment fault the sixteenth cycle fixed one
function away, on the title line of the question screen. The question text
beside it has word-wrapped all along (bg.render_question_screen's textwrap
call). This caption was the last guillotine on these screens.
"""
import importlib.util
import os
import random
import re
import sys
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

_spec = importlib.util.spec_from_file_location(
    "crt_book_game_for_caption_test", os.path.join(BIN_DIR, "crt-book-game.py"))
bg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bg)

_cspec = importlib.util.spec_from_file_location(
    "crt_book_console_for_caption_test", os.path.join(BIN_DIR, "crt-book-console.py"))
console = importlib.util.module_from_spec(_cspec)
_cspec.loader.exec_module(console)

WIDTH, HEIGHT = 40, 15


def screens(n=400, seed=3):
    """Many real draws, rather than a stubbed rng -- the claims below are
    about what any of the six captions does at any of the positions it can
    land in, and a stub that fixes both would test one cell of that grid."""
    rng = random.Random(seed)
    return [[ANSI.sub("", ln) for ln in console.render_idle_screen(3, WIDTH, HEIGHT, rng=rng)]
            for _ in range(n)]


class ColumnWidthTest(unittest.TestCase):
    def test_the_kaomoji_is_wider_than_it_is_long(self):
        # The measurement the old code did not have. If this ever reads 5,
        # the platform's unicodedata disagrees and the rest is moot.
        self.assertEqual(len("(・∀・)"), 5)
        self.assertEqual(bg.display_width("(・∀・)"), 7)

    def test_ascii_is_unchanged(self):
        # Everything else on these screens must be byte-identical to before.
        for s in ("", "Dune", "before / after", "9780451524935 -- x"):
            self.assertEqual(bg.display_width(s), len(s))
            self.assertEqual(bg.center_text(s, 40), s.center(40))

    def test_cut_to_width_never_half_draws_a_wide_character(self):
        # '(・∀' is 4 columns; the next middle dot needs 2 and only 1 is left,
        # so it is dropped whole rather than half-drawn -- leaving a result
        # one column short of the limit, which is why callers pad after
        # cutting instead of trusting the count.
        self.assertEqual(bg.cut_to_width("(・∀・)", 5), "(・∀")
        self.assertEqual(bg.display_width(bg.cut_to_width("(・∀・)", 5)), 4)
        self.assertEqual(bg.cut_to_width("(・∀・)", 6), "(・∀・")   # exactly 6

    def test_a_fullwidth_title_is_padded_to_the_pane_not_past_it(self):
        # An ordinary scan of a Japanese book. Padded by character count this
        # is 40 characters and 66 columns.
        line = bg.center_text("吾輩は猫である", WIDTH)
        self.assertEqual(bg.display_width(line), WIDTH)

    def test_elide_marks_a_wide_cut_too(self):
        out = bg.elide("吾輩は猫である", 8)
        self.assertTrue(out.endswith(".."))
        self.assertLessEqual(bg.display_width(out), 8)

    def test_no_drawn_line_is_wider_than_the_tube(self):
        for screen in screens():
            for ln in screen:
                self.assertEqual(
                    bg.display_width(ln), WIDTH,
                    "a %d-column line on a %d-column tube wraps: %r"
                    % (bg.display_width(ln), WIDTH, ln))


class TheCaptionStillAsksTest(unittest.TestCase):
    def test_every_enticement_line_appears_whole(self):
        """Not 'appears' -- appears with the part that does the asking."""
        drawn = [" ".join(s) for s in screens()]
        for entice in bg.ENTICE_LINES:
            words = entice.split()
            # Every word, somewhere on one screen. The caption may be spread
            # over up to three rows, so this asks for the whole line's
            # content, not for one contiguous run of it.
            self.assertTrue(
                any(all(w in d for w in words) for d in drawn),
                "%r never made it onto a screen whole; the closest was %r"
                % (entice, max(drawn, key=lambda d: sum(w in d for w in words))
                   .strip()))

    def test_the_ask_survives_in_all_of_them(self):
        # The blunt version of the test above: these lines exist to produce
        # a scan, and four of the six had lost the verb.
        drawn = " ".join(" ".join(s) for s in screens())
        for entice in bg.ENTICE_LINES:
            ask = [w for w in entice.split() if "scan" in w or "try" in w]
            for word in ask:
                self.assertIn(word, drawn,
                              "%r is the ask in %r and it is not on screen"
                              % (word, entice))

    def test_the_count_caption_keeps_its_own_ask(self):
        """'12 book(s) registered -- scan one!' is 33 columns and was cut at
        30, losing 'one!' and half of 'scan'. It wraps now, so the ask lands
        on the next row instead of on the floor."""
        rng = random.Random(0)
        drawn = [" ".join(ANSI.sub("", ln) for ln in
                          console.render_idle_screen(12, WIDTH, HEIGHT, rng=rng))
                 for _ in range(60)]
        whole = [d for d in drawn
                 if all(w in d for w in "12 book(s) registered -- scan one!".split())]
        self.assertTrue(whole, "the count caption never appeared whole")

    def test_a_caption_that_still_does_not_fit_says_so(self):
        block = bg.wrap_to_width("word " * 60, bg.MAX_CONTENT_WIDTH, max_lines=3)
        self.assertEqual(len(block), 3)
        self.assertTrue(block[-1].endswith(".."),
                        "dropped text with no sign it was dropped: %r" % block[-1])

    def test_wrapping_keeps_the_double_space_after_the_face(self):
        # Deliberate styling in every kaomoji line; textwrap.wrap would keep
        # it too, but only by accident of its chunking -- pinned here because
        # wrap_to_width re-splits the string itself.
        block = bg.wrap_to_width("(=^-^=)  bored kitty here. bring a book", 30)
        self.assertIn("(=^-^=)  bored", block[0])

    def test_one_enormous_word_is_elided_rather_than_looping(self):
        block = bg.wrap_to_width("x" * 200, 30, max_lines=3)
        self.assertEqual(len(block), 1)
        self.assertEqual(bg.display_width(block[0]), 30)


class TheQuestionScreenIsMeasuredTheSameWayTest(unittest.TestCase):
    """The caption was where the bug was found, not where it ended.

    render_question_screen() and scan_title() do the same arithmetic on the
    same tube, and a book whose title Open Library returns in Japanese is an
    ordinary scan for a feature whose premise is 'scan any book nearby'.
    Fixing only the caption would leave the half-wired state this project
    keeps paying for.
    """

    def _row(self, title, lcc=None):
        return {"title": title, "lcc": lcc}

    def test_a_fullwidth_title_gets_the_call_number_it_can_afford(self):
        # 7 characters, 14 columns. Against a 28-column budget, len() said
        # there was room for the title AND ' (PL800)' and there was not.
        line = console.scan_title(self._row("吾輩は猫である", "PL800"), WIDTH)
        self.assertLessEqual(bg.display_width(line), bg.title_budget(WIDTH))

    def test_a_title_too_wide_for_both_says_it_was_cut(self):
        line = console.scan_title(self._row("吾輩は猫である吾輩は猫である猫", "PL800"), WIDTH)
        self.assertLessEqual(bg.display_width(line), bg.title_budget(WIDTH))
        self.assertIn("..", line)

    def test_the_whole_question_screen_fits_the_pane(self):
        screen = bg.render_question_screen(
            console.scan_title(self._row("吾輩は猫である", "PL800"), WIDTH),
            {"text": "この本は小説ですか、それとも随筆ですか",
             "options": ["小説", "随筆"]},
            WIDTH, HEIGHT)
        self.assertEqual(len(screen), HEIGHT)
        for ln in screen:
            self.assertEqual(bg.display_width(ln), WIDTH,
                             "%d columns on a %d-column tube: %r"
                             % (bg.display_width(ln), WIDTH, ln))

    def test_options_that_do_not_fit_say_so_rather_than_stopping(self):
        screen = bg.render_question_screen(
            "Dune", {"text": "Which?",
                     "options": ["a very long first option indeed",
                                 "and a second one as well"]},
            WIDTH, HEIGHT)
        joined = "".join(screen)
        self.assertIn("..", joined,
                      "the options line was cut with no sign it was cut")

    def test_an_ordinary_question_screen_is_unchanged(self):
        # The wrap swap must be invisible for the ASCII case, which is every
        # question the template generator has ever produced.
        title = console.scan_title(self._row("Nineteen Eighty-Four", "PR6029"), WIDTH)
        screen = bg.render_question_screen(
            title,
            {"text": "Was Nineteen Eighty-Four published before or after 1950?",
             "options": ["before", "after"]}, WIDTH, HEIGHT)
        body = [ln.strip() for ln in screen if ln.strip()]
        # Byte-for-byte the screen the sixteenth cycle's report printed.
        self.assertEqual(body, ["Nineteen Eighty-F.. (PR6029)",
                                "Was Nineteen Eighty-Four",
                                "published before or after",
                                "1950?", "before / after"])
        self.assertTrue(all(len(ln) == WIDTH for ln in screen))


class TheCaptionStillMovesTest(unittest.TestCase):
    """The 2026-07-21 asks the wrap must not undo."""

    def test_it_still_lands_on_different_rows(self):
        rows = set()
        for screen in screens(200, seed=5):
            for i, ln in enumerate(screen):
                if "book" in ln or "kitty" in ln or "quiet" in ln:
                    rows.add(i)
        self.assertGreater(len(rows), 2, "the caption stopped moving")

    def test_it_never_lands_on_the_shelf(self):
        art = [l for l in bg.get_ascii_art("shelf").splitlines() if l.strip()]
        for screen in screens(200, seed=9):
            for art_line in art:
                self.assertTrue(
                    any(art_line.strip() in ln for ln in screen),
                    "a multi-row caption wrote through the shelf art: %r"
                    % [ln for ln in screen if ln.strip()])

    def test_it_still_uses_all_three_alignments(self):
        starts = set()
        for screen in screens(200, seed=13):
            for ln in screen:
                if "book" in ln and "BOOK GAME" not in ln:
                    starts.add(len(ln) - len(ln.lstrip()))
        self.assertGreater(len(starts), 1, "the caption stopped moving sideways")


if __name__ == "__main__":
    unittest.main()
