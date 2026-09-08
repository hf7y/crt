# Book Game: a training-data game (vision 2026-07-21, shipped same day, running on `potato`)

See `BOOK-GAME-STYLE.md` for personality/animation/screen-layout/color and
`SCANNER.md` for how a scan physically reaches this game.

## Why this exists

The console needs a way to collect **structured** speech samples — known
expected text, known actual transcription — cheaply and continuously. This
game's mechanic *is* that: "say this specific word/phrase, we already know
what you should be saying." It's byproduct-first — playable on its own, and
every round also produces a labeled (expected, heard) pair.

## The loop

Scan a book's ISBN (USB HID scanner, no driver) → look up title/author/facts
(Open Library/Google Books, cached) → ask a 2-option question about the book
→ listen for the spoken answer via the existing mic pipeline → grade it
exact-ish (normalize, don't fuzzy-match) → register the book (ISBN, facts,
this round's result) into a local SQLite catalog, independent of the game
itself ("my library" via `crt-book-catalog.py` / `crt-secretary.py`).

Grading tracks two axes, not one: `correct_content` (did they know the book
fact) and `correct_stt` (did the mic hear an option that was on offer,
`null` if no option list was recorded). They can disagree — a right-content,
wrong-STT round is the valuable training case. See `grade_answer()`'s
docstring in `bin/crt-book-game.py` for exactly how `correct_stt` is judged.

Question generation mixes deterministic templates with batched,
cached Claude-authored questions (~50/50, batched per-scan-burst rather than
one live call per book) — see `build_claude_batch_prompt()`/
`parse_claude_batch_response()` in `bin/crt-book-game.py`.

## Scanner delivery: two paths, one of them a live finding

`SCANNER.md`'s dexter-bridge (network, `[scan] <isbn>` into tmux) is one
path. The one actually used in practice is simpler: the scanner is HID
keyboard input ending in Enter, and raw scan keystrokes reach **whichever
tmux window currently has focus**, not a specific one — `crt-book-console.py`
reads stdin directly rather than needing to be targeted.

## What's live now

Built and running on `potato`, standalone-first then wired into
`crt-console.sh`'s `book`/`bookanswer` windows:

- `bin/crt-book-game.py` — lookup, question generation, grading, SQLite
  registry, best-effort LCC. `tests/test_book_game.py`,
  `tests/test_book_game_stt_axis.py`.
- `bin/crt-book-console.py` — the `book` tmux window: tails the scanner log,
  renders the question screen. `tests/test_book_console.py`.
- `bin/crt-book-answer-listen.py` — the `bookanswer` window: watches
  `~/.crt/stt.log` and grades the next utterance automatically, within
  `CRT_BOOK_ANSWER_WINDOW_SECS` of a scan.
- `bin/crt-book-catalog.py` — "my library" catalog view/playbook.
  `tests/test_book_catalog.py`.

**Resolved v1 decision:** no label printer. The LCC call number, when
computed, displays in the question screen's title line instead
(`crt-book-console.py`'s `render_scan_result()`) — revisit physical labels
only if Bluetooth-through-VM printing gets solved some other way.

**Not yet eye-verified on the real tube** — same caveat as
`BOOK-GAME-STYLE.md`'s own Status section.

## Open

`bin/crt-midi-knobs.py` is unrelated hardware still not verified on any
current host — its own header covers the how and current status.
