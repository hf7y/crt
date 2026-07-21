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

## Idle-bait: two registers, not one (updated 2026-07-21 — this is the actual point)

**The whole feature's purpose, stated plainly (2026-07-21 direction):**
idle-bait exists to entice someone into picking up a book and scanning
it — everything downstream (the question, the spoken answer, the STT
training log) only happens once that scan occurs. A quote celebrating a
book ALREADY scanned is a nice flourish, but it is not the mechanism that
gets a NEW scan to happen. `bin/crt-book-idle-bait.py` and
`bin/crt-book-console.py`'s idle screen both now mix two distinct lines,
not just one:

- **Enticement lines** (`pick_entice_line()`, `ENTICE_LINES` — kaomoji,
  same voice as `crt-idle-bait.sh`'s existing `(=^-^=)` jokes): actively
  invite a new scan ("got a book nearby? scan it..."). Always available,
  even with a completely empty registry — **fixed a real gap**: before
  this pass, an empty `books.db` meant `pick_and_format_line()` (formerly
  `pick_and_format_quote_line`) silently returned nothing at all, so a
  fresh install had zero idle-bait until the first scan ever happened.
  Now the empty-registry case always shows an enticement line.
- **Quote lines** (`pick_idle_quote()`, unchanged from before): celebrate
  a book already scanned — Open Library's cached `first_sentence`, a
  freshly-scraped Wikiquote line (see below), or the static
  `FALLBACK_QUOTES` pool as a last resort, in that priority order.
- **Mixing rule**: `CRT_BOOK_ENTICE_RATE` (default 0.4 in the thoughts-log
  idle-bait, a flat 0.5 in the `book` window's idle screen) — even once
  books exist, idle-bait keeps pulling toward NEW scans instead of only
  ever showing off old ones.
- **Deliberately not a Claude call**, either register. Enticement lines
  are static text; quote lines only ever read `books.db` (cached at scan
  time) or the local fallback pool. Matches this project's "minimize/tune
  live API usage" principle (`CLAUDE.md`) applied to a place that
  doesn't need Claude at all.
- Enticement lines render in `COLOR_QUESTION` (warm/curious — inviting,
  not urgent); quote lines stay `COLOR_QUOTE` (dim magenta, wistful/
  quiet) — same register-color convention as `crt-idle-teaser.sh`'s
  `color_for_line()`.

### Real per-book quotes (webscrape, not AI, added 2026-07-21)

`scrape_quote()` pulls an actual quote from Wikiquote's MediaWiki API at
registration time (search → page wikitext → parse top-level `* text`
bullet lines as quotes, `** text` as attributions to skip, strip
`[[wiki|links]]`/`'''bold'''` markup) — literal scraped text, **not** an
AI paraphrase, per explicit direction. Cached once in a new `quote`
column in `books.db`, never re-scraped on a re-scan. Wrapped in a broad
try/except so a slow/unreachable Wikiquote can never block or crash a
scan — falls through to `first_sentence` then the static pool instead.
`pick_idle_quote()`'s priority order is: cached scrape → `first_sentence`
→ static pool.

## ASCII art library

`ASCII_ART` in `crt-book-game.py` is a small hand-curated set (`book`,
`cat_reading`, `bookworm`, `shelf`, plus kawaii/kaomoji entries
`kawaii_cat`/`kawaii_owl`/`kawaii_sleepy` added 2026-07-21) in the same
bare-line-art style as `crt-screensaver.py`'s existing `FRAMES` — the
kind of unattributed
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
registered so far" flourish.

**`bookworm` wired in, 2026-07-21**: `crt-book-answer-listen.py`'s
`format_result_line()` now appends the `bookworm` art to a correct-
answer announcement — this exact pairing was named here when the art
library was built, but nothing ever actually used any art besides
`shelf` (in the idle screen) until now. `book`/`cat_reading` remain
unwired — both would need a scan-in-progress/waiting state the current
single-screen-per-event render model (`crt-book-console.py`) doesn't
have yet (it renders one full screen per event: idle, question, or
error — no intermediate "scanning..." or "waiting for your answer..."
state to attach transitional art to). Real follow-up if that render
model ever grows a waiting state, not attempted this pass.

## Colors: register-matched, and NEVER primary red/green/blue

**Persistent flag, read this before changing book-game colors:** this
project's display is a real analog CRT tube (`DISPLAY-CALIBRATION.md`),
driven over composite/RF, not a digital panel. Composite/RF video has
far less chroma (color) bandwidth than luma (brightness) — the classic
symptom is **fully-saturated primaries bleeding, smearing, or ringing**.
This is real broadcast-video physics, the same reason old TV graphics
avoided pure saturated primary text — **not a stylistic choice that can
be "improved" later.** The same flag is now also in `CLAUDE.md` so it
isn't lost if this file is never opened again.

**HARD RULE, updated 2026-07-21 (Zach, confirmed live) — this is
stricter than the original version of this section said:** it is NOT
just the bright/bold family (91/92/94) that bleeds — **standard-
intensity red (31), green (32), and blue (34) render badly too, at any
boldness/dimness.** Never use ANSI codes 31, 32, 34, 91, 92, or 94
anywhere in this project's screen output. Only yellow (33), magenta
(35), cyan (36), and white (37) — plus dim/bold modifiers on those —
are CRT-safe.

The book-game palette (`crt-book-game.py`), reassigned to comply with
the corrected rule above (previously `COLOR_CORRECT`/`COLOR_WRONG` used
plain green/red, which violated it):

| Constant | ANSI | Register | Used for |
|---|---|---|---|
| `COLOR_QUESTION` | `33` (yellow) | warm/curious | posing a question |
| `COLOR_CORRECT` | `1;37` (bold white) | content/settled | right answer |
| `COLOR_WRONG` | `35` (magenta) | clipped | wrong answer |
| `COLOR_QUOTE` | `2;36` (dim cyan) | wistful/quiet | idle-bait quote |
| `COLOR_TITLE` | `36` (cyan) | curious | book title |

Mechanically enforced by `tests/test_book_game.py`'s
`test_no_primary_rgb_codes_in_palette` — checks every code in the
palette against the banned set (31/32/34/91/92/94), not just the bright
half, so a future edit can't accidentally reintroduce the exact bleed
this section warns about.

## Screen real estate: content capped at 30 characters (hard rule, 2026-07-21)

Also confirmed live by Zach: actual text content should never span more
than **30 characters**, even though the screen itself is nominally
40 columns wide — `MAX_CONTENT_WIDTH` in `crt-book-game.py`. Lines still
get padded to the full detected/fallback screen width for a consistent
layout; only the title/question/options/caption TEXT itself is wrapped/
truncated against `min(width, 30)` before centering. Applied in
`render_question_screen()` (the shared question-screen renderer) and
`crt-book-console.py`'s `render_idle_screen()`/`render_answer_result()`.

## Idle screen: caption moves around, not fixed in the center (2026-07-21)

The idle screen's caption (entice line or book count) used to always
render at the same fixed row, centered, directly under the shelf art —
Zach's direct ask: "move around the screen with idle bait rather than
render in center every time." `render_idle_screen()` now picks a random
row each draw (never overlapping the title row or the shelf art itself)
and a random left/center/right alignment via a new `_place_text()`
helper, so the resting screen doesn't look frozen in the same layout
every time.

## Status

Built and tested this pass (screen layout, ASCII art, color palette,
non-API idle-bait quotes) — all offline, all in
`tests/test_book_game.py` / `tests/test_book_idle_bait.py`. **Not yet
verified against a real tube** — every color/centering/art choice above
is a hypothesis about what reads well at 40x15 on real phosphor, same
caveat as `EXPRESSIVE-TONE.md`'s own audio register table. Needs a
human eye on the actual CRT before any of this is called final.
