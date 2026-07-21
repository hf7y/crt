# Book Game: personality, animation, and style guide

Companion to `BOOK-GAME.md` (mechanics/roadmap) and `SCANNER.md` (how a
scan physically arrives). This doc covers the part those two don't:
**how a round should feel and look** on a screen with almost no room to
say anything. All of it is offline-buildable and covered by
`tests/test_book_game.py`/`test_book_idle_bait.py` — nothing here needs
a live tube to write or test, only to finally *look at*.

## Personality: a quiz-show host who's also the librarian

Per `CLAUDE.md`'s base persona (terse, playful, plays with mishears
rather than getting clinical about them) and `EXPRESSIVE-TONE.md`'s
register taxonomy, the Book Game is a distinct **mode** of the same
voice, not a new character:

- **Warm/curious** for posing a question — inviting, a little
  competitive, like a game-show host who already knows the answer and
  is enjoying watching you guess. Text example: `Fiction or nonfiction,
  make the call:` not `Please answer: is this book fiction or
  nonfiction?`
- **Content/settled** for a correct answer — short, satisfied, no
  gloating. `got it.` is enough.
- **Clipped** for a wrong answer — per `EXPRESSIVE-TONE.md`, this is
  NOT the urgent/blocker register (nothing's actually wrong), just the
  shorter/flatter shape: `nope, it was {answer}.` Never a sad-trombone
  tone — this is a game, wrong answers are half the fun of playing.
- **Wistful/quiet** for idle-bait quotes (below) — the librarian half of
  the persona, thumbing through the stacks while no one's around.

Same voice as the rest of the console, just wearing this game's specific
hat — consistent with `PERSONA-CHANNEL.md`'s "one body, several selves."

## Screen real estate

The CRT is `~40x15` characters (`CLAUDE.md`) and every renderer in this
repo (`crt-pager.py`, `crt-monologue.py`, `crt-present-morning-report.py`)
already treats that as **two tunable variables, not a hardcoded
constant** — `crt-book-game.py` follows the exact same convention:

```
CRT_BOOK_GAME_WIDTH / CRT_BOOK_GAME_HEIGHT   # env override, wins if both set
shutil.get_terminal_size()                    # real terminal, if no override
40 x 15                                       # CLAUDE.md fallback, last resort
```

`detect_screen_size()` in `crt-book-game.py` implements this precisely
the way `crt-pager.py`'s `detect_size()` does — deliberately not a new
pattern, so a future safe-margin/overscan pass
(`DISPLAY-CALIBRATION.md`) can wire book-game rendering into the same
margin config (`~/.crt/display.conf`) other renderers already read,
without this file needing a rewrite.

### Questions are centered, not top-anchored

`render_question_screen(book_title, question, width, height)` lays out:
- row 0: the book title, centered
- vertical middle: the question text (word-wrapped, centered line by
  line) then a blank line then the two options, centered, joined
  `option_a / option_b`
- everything else: blank padding

Centering the *question*, not the title or a menu chrome, matches
`CLAUDE.md`'s "lead with the answer, no preamble" — the thing your eye
should land on first is the thing you're being asked, not a header.

## Idle-bait quotes (non-API, built this pass)

`bin/crt-book-idle-bait.py` pops a cached book quote into
`~/.crt/thoughts.log` after a quiet stretch, same mechanism as
`bin/crt-idle-bait.sh`'s cat jokes but sourced from the book registry
instead of a hardcoded joke list:

- `extract_quote()` pulls Open Library's `first_sentence` field out of
  the **already-cached** raw response in `books.db` — no new network
  call, since that data was fetched once at scan time.
- If a book has no cached first sentence (most ISBN-endpoint lookups
  don't), `pick_idle_quote()` falls back to a small local
  `FALLBACK_QUOTES` pool, picked **deterministically per-ISBN**
  (sha256-seeded index, not re-randomized every call) so the same book
  always surfaces the same flavor line rather than feeling random.
- **Deliberately not a Claude call.** Per direction, idle-bait quotes
  are a zero-marginal-cost feature — every token this feature will ever
  cost was already spent once, at scan time, fetching the metadata that
  might contain a real quote. Matches this project's own "minimize/tune
  live API usage" principle (`CLAUDE.md`, `BOOK-GAME.md`'s
  question-generation section) applied to a place that doesn't strictly
  need Claude at all.
- Rendered in `COLOR_QUOTE` (dim magenta, wistful/quiet register) via
  `wrap_color()`, same convention as `crt-idle-teaser.sh`'s
  `color_for_line()`.

## ASCII art library

`ASCII_ART` in `crt-book-game.py` is a small hand-curated set (`book`,
`cat_reading`, `bookworm`, `shelf`) in the same bare-line-art style as
`crt-screensaver.py`'s existing `FRAMES` — the kind of unattributed
line-art that's been shared across ASCII-art collections for decades,
not machine-scraped from a specific live URL. **Why not literally fetch
from the internet at build or run time**: this project's offline-safe
acceptance bar (`BOOK-GAME.md`, `FOCUS.md`) means nothing can depend on
a fetch succeeding at the exact moment it's shown — a scan round is not
the place to introduce a new possible network failure for a cosmetic
flourish. `get_ascii_art(name)` returns `None` for an unknown name so a
missing/renamed entry degrades to "no art this round," never a crash.

Each entry is sized to fit inside the 40-wide fallback screen (asserted
in `tests/test_book_game.py`). Suggested use, once wired into a live
session: `book` on a fresh scan, `cat_reading` while waiting on an
answer, `bookworm` on a correct answer, `shelf` as a periodic "N books
registered so far" flourish — none of that wiring is built yet
(`BOOK-GAME.md` roadmap step 3, needs the standalone CLI proven first).

## Colors: register-matched, and NOT primary colors

**Persistent flag, read this before changing book-game colors:** this
project's display is a real analog CRT tube (`DISPLAY-CALIBRATION.md`),
driven over composite/RF, not a digital panel. Composite/RF video has
far less chroma (color) bandwidth than luma (brightness) — the classic
symptom is **fully-saturated primaries bleeding, smearing, or ringing**,
worst on bright/bold red, and worst of all at a hard edge between
complementary hues (red next to cyan). This is real broadcast-video
physics, the same reason old TV graphics avoided pure saturated red
text — **not a stylistic choice that can be "improved" later by going
brighter/bolder.** The same flag is now also in `CLAUDE.md` so it isn't
lost if this file is never opened again.

The book-game palette (`crt-book-game.py`) deliberately reuses
`crt-idle-teaser.sh`'s existing register colors rather than inventing a
parallel scheme (`EXPRESSIVE-TONE.md`'s color dimension, one taxonomy
project-wide):

| Constant | ANSI | Register | Used for |
|---|---|---|---|
| `COLOR_QUESTION` | `33` (std yellow) | warm/curious | posing a question |
| `COLOR_CORRECT` | `32` (std green) | content/settled | right answer |
| `COLOR_WRONG` | `31` (std red) | clipped | wrong answer |
| `COLOR_QUOTE` | `2;35` (dim magenta) | wistful/quiet | idle-bait quote |
| `COLOR_TITLE` | `36` (std cyan) | curious | book title |

All five are **standard-intensity** ANSI codes (30-37), never the
bright/bold family (90-97) — `tests/test_book_game.py`'s
`test_no_bright_ansi_codes_in_palette` asserts this mechanically so a
future edit can't accidentally reach for `\033[91m` "brighter red" and
reintroduce the exact bleed this section warns about.

## Status

Built and tested this pass (screen layout, ASCII art, color palette,
non-API idle-bait quotes) — all offline, all in
`tests/test_book_game.py` / `tests/test_book_idle_bait.py`. **Not yet
verified against a real tube** — every color/centering/art choice above
is a hypothesis about what reads well at 40x15 on real phosphor, same
caveat as `EXPRESSIVE-TONE.md`'s own audio register table. Needs a
human eye on the actual CRT before any of this is called final.
