# Investigation: trivia always asks the same "before/after 199X" question

Branch: `investigate/trivia-question-variety`. Zach reported the trivia
always asks a variant of "was this published before or after 199X" and
never varies, and never calls out to Claude. Diagnosed live against the
real Open Library API (not guessed) — two separate, confirmed causes.

## Cause 1 (confirmed bug, fixed here): author extraction was broken

`fetch_book_metadata()` only checked `data["author_names"]` and
`data["authors"]` for author info. Tested live against 5 real ISBNs —
**every one** came back `authors: ['Unknown']`. Pulled the raw JSON
directly (`curl openlibrary.org/isbn/<isbn>.json`) and found the real
shape this endpoint actually returns:

1. `"author": ["Orwell, George, 1903-1950."]` — a **different key**
   (`author`, singular) than either of the two the code checked,
   containing plain `"Last, First, dates."` strings. This is the common
   case in my sample (2 of 5 books) and was **never checked at all**.
2. `"authors": [{"key": "/authors/OL498120A"}]` — a bare reference with
   **no embedded name**, needing a second API call to resolve. Not
   fixed here (see "Not fixed" below).
3. No author field at all (1 of 5) — genuinely absent upstream.

Since `generate_template_question()`'s author-name question requires
`authors[0] != "Unknown"` to even be a candidate, and authors were
*always* `"Unknown"` in practice, that question could **never fire** —
every real scan was starved down to just the year-based question
(the only one that doesn't depend on `authors`/`subjects`, both of which
are frequently absent from this endpoint). That's why it always looked
like "the same question": it structurally was, just with the specific
decade varying by book — and if several test scans happened to land in
the 1985–1994 range, "before or after 1990" specifically would repeat.

**Fixed**: `fetch_book_metadata()` now also checks `data["author"]`, and
a new `_clean_author_name()` reformats `"Last, First, dates."` → `"First
Last"` (needed both for display and because the first-name-extraction
logic assumes `"First Last"` word order). **Verified live**: re-ran
against Orwell, Coelho, and Austen — all three now resolve real names,
and `generate_template_question()` now actually produces author-name
questions in the mix, confirmed by direct repeated sampling.

9 new tests (`TestMetadataLookup`/`TestCleanAuthorName` additions in
`tests/test_book_game.py`), full suite green (`bash tests/run_tests.sh`).

## Cause 2 (documented design, not a new bug): Claude is genuinely never called

`pick_question_source()` is called in both `crt-book-console.py`'s
`handle_scan()` and `crt-book-game.py`'s CLI `main()` — but its return
value (`"claude"` or `"template"`) is only ever **stored** in
`books.db`'s `question_source` column, never actually branched on.
Both call sites unconditionally call `generate_template_question()`
regardless of what `pick_question_source()` returned. This matches
`BOOK-GAME.md`'s own roadmap note (step 1): *"the actual `claude -p`
invocation needs the same hands-on wiring as `crt-secretary.py`'s
Claude-routing path... this standalone CLI always uses the template
path"* — a deliberate, already-documented deferral, not something that
silently broke. **Not fixed in this pass** — wiring a real `claude -p`
batch call is separate, larger work (needs the same tmux send-keys/
capture-pane pattern `crt-secretary.py` uses, plus the batching/caching
logic `build_claude_batch_prompt()`/`parse_claude_batch_response()`
already scaffold) and wasn't asked for here; flagging clearly so cause 1
isn't mistaken for the whole explanation.

## Status

Branch only — not merged to `main`, since Zach is troubleshooting STT
there live. Author-extraction fix is tested and verified live; ready to
merge whenever convenient. The Claude-wiring gap remains open, tracked
here and in `BOOK-GAME.md`'s existing roadmap note, not attempted this
pass.
