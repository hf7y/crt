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
hat — consistent with `vault:crt/PERSONA-CHANNEL.md`'s "one body, several selves."

## Screen real estate

The CRT is `~40x15` (`CLAUDE.md`), treated as tunable, not hardcoded, same
convention as every other renderer in this repo. `detect_screen_size()` in
`crt-book-game.py` carries the full resolution-chain and re-measure-every-
tick rationale in its own docstring — deliberately the same pattern as
`crt-pager.py`'s `detect_size()`, so a future `DISPLAY-CALIBRATION.md`
margin pass can wire book-game in without a rewrite.
`tests/test_book_console_size.py` proves the resize-mid-session case on a
real pty.

`render_question_screen(book_title, question, width, height)` centers the
*question* (title top, question+options in the vertical middle) rather
than a header or menu chrome — matches `CLAUDE.md`'s "lead with the
answer." Its own docstring in `crt-book-game.py` has the exact layout.

## Idle-bait: two registers, not one

The point: idle-bait exists to entice someone into picking up a book and
scanning it — a quote celebrating a book already scanned is a flourish,
not the mechanism that gets a NEW scan. `pick_entice_line()`/
`ENTICE_LINES` (kaomoji, same voice as `crt-idle-bait.sh`) always invite a
new scan, even against an empty registry; `pick_idle_quote()` celebrates
an already-scanned book (cached Wikiquote line → Open Library
`first_sentence` → static `FALLBACK_QUOTES`, in that order —
`scrape_quote()`'s own docstring in `crt-book-game.py` has the fetch/
cache detail). `CRT_BOOK_ENTICE_RATE` mixes the two. Neither register is
a Claude call — enticement is static text, quotes only ever read
`books.db` or the local pool. Enticement renders `COLOR_QUESTION`, quotes
stay `COLOR_QUOTE`.

## ASCII art library

`ASCII_ART` in `crt-book-game.py`: `book`, `cat_reading`, `bookworm`,
`shelf`, plus kawaii/kaomoji entries — hand-curated, same
unattributed-line-art convention as `crt-screensaver.py`'s `FRAMES`,
never fetched live (this project's offline-safe bar). `get_ascii_art(name)`
returns `None` for an unknown name, so a missing/renamed entry degrades
to no art rather than a crash. Each entry fits the 40-wide fallback
screen (asserted in `tests/test_book_game.py`).

Wired in: `shelf` in the idle screen, `bookworm` on a correct answer
(`crt-book-answer-listen.py`'s `format_result_line()`). `book`/
`cat_reading` are suggested for a scan-in-progress/waiting state that
`crt-book-console.py`'s current one-screen-per-event render model
doesn't have yet — real follow-up if that model grows one, not built.

## Colors: register-matched, and NEVER primary red/green/blue

**Persistent flag, read this before changing book-game colors:** this
project's display is a real analog CRT over composite/RF — far less
chroma bandwidth than luma, so fully-saturated primaries bleed, smear,
or ring. Real broadcast-video physics, not a stylistic choice
(`CLAUDE.md` carries the same flag project-wide). **Never use ANSI 31,
32, 34, 91, 92, or 94 anywhere in this project's screen output** — only
33/35/36/37 (yellow/magenta/cyan/white) plus dim/bold modifiers.

The book-game palette (`crt-book-game.py`):

| Constant | ANSI | Register | Used for |
|---|---|---|---|
| `COLOR_QUESTION` | `33` (yellow) | warm/curious | posing a question |
| `COLOR_CORRECT` | `1;37` (bold white) | content/settled | right answer |
| `COLOR_WRONG` | `35` (magenta) | clipped | wrong answer |
| `COLOR_QUOTE` | `2;36` (dim cyan) | wistful/quiet | idle-bait quote |
| `COLOR_TITLE` | `36` (cyan) | curious | book title |

Mechanically enforced by `tests/test_book_game.py`'s
`test_no_primary_rgb_codes_in_palette` against the full banned set.

Content itself (title/question/options/caption text, not padding) is
capped at `MAX_CONTENT_WIDTH` (30 columns, hard rule) even on a wider
screen — `render_question_screen()` and `crt-book-console.py`'s
`render_idle_screen()`/`render_answer_result()` all wrap/truncate
against it before centering.

The idle screen's caption (entice line or book count) picks a random row
and left/center/right alignment each draw rather than a fixed centered
spot — `render_idle_screen()`'s own docstring in `crt-book-console.py`
has the placement logic.

## Status

Built and tested this pass (screen layout, ASCII art, color palette,
non-API idle-bait quotes) — all offline, all in
`tests/test_book_game.py` / `tests/test_book_idle_bait.py`. **Not yet
verified against a real tube** — every color/centering/art choice above
is a hypothesis about what reads well at 40x15 on real phosphor, same
caveat as `EXPRESSIVE-TONE.md`'s own audio register table. Needs a
human eye on the actual CRT before any of this is called final.
