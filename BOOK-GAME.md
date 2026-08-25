# Book Game: a training-data game for crt-vm (2026-07-21, vision)

See `BOOK-GAME-STYLE.md` for personality/animation/screen-layout/color
style guide (built 2026-07-21) and `SCANNER.md` for how a scan physically
reaches this game.

## Why this exists

Every other crt document (`FOCUS.md`'s top vision entry, `PARKING-LOT.md`)
already names the same problem from the language-tree/STT side: the
console needs a way to collect **structured** speech samples — known
expected text, known actual transcription — cheaply and continuously,
not just raw room audio. "Games and idle bait are important ways of
requesting specific sonic information in a structured way that informs
the voice detection model" (`FOCUS.md`, 2026-07-20 15:57). This is the
first concrete instance of that idea: a game whose entire mechanic
*is* "say this specific word/phrase, we already know what you should be
saying." It's a byproduct-first design — the game is real and playable on
its own, and every round happens to also produce a labeled (expected,
heard) pair.

## The loop

1. **Scan.** A USB HID 1D barcode scanner (types like a keyboard —
   scan → newline, no driver needed) reads a book's ISBN barcode.
2. **Lookup.** ISBN → title/author/subject/etc. via a book-metadata API
   (Open Library and/or Google Books — both have free ISBN lookup
   endpoints, no key needed for Open Library). Cache the raw response.
3. **Ask.** Generate a 2-option multiple-choice question from the book's
   facts ("Published before or after 2000?", "Is the author's first name
   Ray or Roy?", "Fiction or nonfiction?"). One option is correct. See
   "Question generation: salted, cached, batched Claude calls" below for
   how deterministic templates and occasional Claude-authored questions
   mix.
4. **Listen.** User speaks their answer into the existing mic pipeline.
   STT transcribes it.
5. **Grade.** Compare the transcription against the two known option
   strings — this is a **closed 2-way classification**, not open
   transcription grading, which is exactly what makes this a good STT
   training signal: the correct answer is known in advance, so every
   round yields a labeled (expected utterance, actual STT output) pair
   whether the user was right or wrong about the book trivia itself.
6. **Register.** The book (ISBN, title, author, facts, timestamp, and
   this session's Q&A result) gets appended to a local registry —
   "documents the books for safe keeping" per the vision, i.e. this
   doubles as a personal library catalog, independent of the game.
   **Actually viewable now, 2026-07-21** (this vision line held true in
   `books.db` from day one, but there was no way to actually SEE the
   catalog until now): `bin/crt-book-catalog.py` (`screen`/`print-all`
   modes) plus a `book_catalog` `crt-secretary.py` playbook ("my
   library", "book catalog", "list my books") — most recently scanned
   first, title/author(s)/year/best-effort LCC per book.
7. **(Stretch) Print.** Send an LCC (Library of Congress Classification)
   call number label to a connected label printer, so each scanned book
   gets a physical spine label — turning the registry into an actual
   organized shelf, not just a database.

## Per-answer grading: exact-ish, mismatches are training data

Per direction: grade close to literal (normalize case/punctuation/
whitespace, but don't fuzzy-match past that), and **every mismatch
between the expected option string and what STT actually heard is logged
verbatim as training data**, not silently absorbed. This is a deliberate
divergence from `PARKING-LOT.md`'s "transcription errors get silently
absorbed" end-state philosophy — that principle is about the *secretary*
persona's outward feel; this game is explicitly the diagnostic instrument
that principle depends on existing somewhere. The log this produces is
exactly the STT gate work's missing ingredient (`FOCUS.md`'s "Now (core
STT)" section) — real labeled utterances instead of ambient guesswork.

Log shape (`~/.crt/book-game-training.jsonl`, one line per round):
```json
{"ts": "...", "isbn": "...", "expected": "fiction", "heard": "friction",
 "correct_content": true, "correct_stt": false}
```
`correct_content` (did they know the book fact) and `correct_stt` (did
the mic hear them right) are tracked as two separate axes — a wrong
content-answer with correct STT is a fine game round and useless
training noise; a right content-answer with wrong STT is the valuable
case (proves the mismatch is transcription, not the user being unsure).

**How `correct_stt` is actually decided (2026-07-25, fourteenth nightly
cycle).** It is `true` when the transcription is one of the options the
person was just offered, `false` when it is none of them, and `null` when
no option list was recorded, so there is nothing to judge it against.
Nobody but the speaker knows which option they *meant*; what this side can
honestly tell is whether whisper produced something on the list. Until
that date `correct_stt` was `normalize(expected) == normalize(heard)`,
and since both live callers pass the correct option as *both* `expected`
and `correct_option`, it was a duplicate of `correct_content` — the two
axes above could not disagree, so an honest wrong guess ("nonfiction")
was filed as a mishear, counted against STT accuracy, and fed to
`generate_candidate_fixups()`. See `grade_answer`'s docstring in
`bin/crt-book-game.py` for the full account.

## Question generation: salted, cached, batched Claude calls (2026-07-21, Zach)

Not a pure-template system. Direction: **deterministic templates are the
reliable base; Claude-authored questions are a token-aware flavor
layer**, mixed in roughly half the time, never issued as one solo call
per book if a cheaper batched option exists.

- **Per-book source decision**: when a book is freshly scanned (cache
  miss), flip a weighted coin (~50/50, tunable) — deterministic template
  or Claude-authored.
- **Claude calls are per-batch, not per-book, and produce 3 questions at
  once.** A single call's prompt carries metadata for *every* book
  currently pending a question (every book that rolled "Claude" this
  session, plus optionally some that rolled "template" — bundling a
  template-slated book into an in-flight batch is fine and encouraged
  when it doesn't cost extra, since the marginal token cost of one more
  book's metadata in an already-open prompt is far below a solo call)
  and asks for 3 two-option questions per book, correct answer marked,
  returned as one JSON blob keyed by ISBN. Exactly how "pending" batches
  get flushed (a short debounce window per game session? end of a scan
  burst? a size cap?) is an implementation-time policy call, not
  something that needs to be nailed down in this vision doc — the
  offline-buildable unit is "given N books' metadata, return questions
  for all of them," independent of when the batch gets assembled.
- **Cache everything.** Once a book has generated questions (either
  source), store them in the registry keyed by ISBN — a re-scan of the
  same book never re-queries Claude or re-computes templates. This is
  the same "cache the raw lookup response" principle already applied to
  the ISBN metadata call, just extended to the questions themselves.
- **Why this shape**: matches the project's own stated direction of
  minimizing/tuning live API usage by default (`CLAUDE.md`'s "token
  usage of claude calls should be minimized by default and tunable,"
  `FOCUS.md`'s STT-gate long-term item about reducing live calls) while
  still getting real API-generated variety ("flavor") rather than the
  game feeling like a fixed quiz bank forever. The batching-across-books
  behavior is the same instinct as the STT gate's own escalate-only-
  when-unsure design, just applied to a different call site.
- **Offline-buildable now**: the source-decision coin flip, the cache
  read/write, and the batch-prompt-construction/response-parsing logic
  are all pure functions/mockable-HTTP, same as the rest of this list.
  Only the actual live Claude Code invocation (however it's shelled out
  — likely `claude -p` the same way `crt-secretary.py` already routes
  Claude-bound requests) needs real wiring during the hands-on phase;
  build it behind a pluggable question-source interface so the offline
  pass can fully exercise the decision/cache/batch logic against a
  stubbed Claude response.

## Registry: local file, not a new project

Lives under `~/.crt/books.db` (SQLite — simple schema, no server, matches
the existing `~/.crt/*.log`/`*.conf` convention already established by
`crt-stt-solo.py`'s control file and `tts.conf`). One row per scanned
book: ISBN, title, author, raw lookup JSON (cache, avoid re-querying the
same barcode), first-scanned timestamp, LCC call number once computed,
label-printed flag. This stays inside the `crt` repo/runtime as a new
subsystem (`bin/crt-book-game.py` + this registry), not a separate
project — it's a delivery surface for crt's existing hardware and STT
pipeline, same category as `crt-secretary.py` or `crt-pager.py`, not a
different product.

## Build shape: standalone first, merge later

Per direction, build `bin/crt-book-game.py` as its own self-contained
program — own loop (scan → lookup → question → listen → grade →
register), runnable directly on `crt-vm` against the real scanner/mic —
**before** wiring it into the tmux console layout (`crt-console.sh`)
or the secretary playbook dispatcher (`crt-secretary.py`). This matches
how `crt-stt-speakback.sh` and `crt-secretary.py` were both built and
proven standalone before `HANDOFF.md`'s "current running" layout absorbed
them. Only after it works stand-alone does wiring it in as a tmux
window/mode or a secretary playbook ("hey claude, book game") become the
right next step — don't build the integration and the game logic at the
same time.

## What's genuinely offline-buildable right now (no VM, no scanner, no live mic)

Everything in the loop above except step 4 (live mic capture) and the
physical scanner itself is buildable and unit-testable today, the same
way the 2026-07-20 STT-gate work was:
- ISBN → metadata lookup client (mockable HTTP, real API, cacheable).
- Question generator from a book-facts dict (pure function, easy to
  test against fixture book records).
- Grading logic: normalize + exact-ish compare + JSONL logging (pure
  function — feed it (expected, heard) string pairs, assert the log
  line and correct_content/correct_stt flags).
- SQLite registry read/write (real sqlite3, temp db in tests, no
  hardware).
- LCC call-number computation from subject/author (a real, well-defined
  algorithm — Library of Congress classification outline is public;
  this is a pure function once the book's subject/author are known).
Only the barcode-scanner input path (trivially fake-able — a HID scanner
is just keyboard input ending in Enter, so a test can pipe a string) and
the live STT capture need real hardware to verify by ear/hand. The
nightly-batch unattended tier can build and test everything except the
final "does this feel fun and did the scanner actually work" pass.

## Stretch goal: LCC label printing

Needs a connected label printer — `SECRETARY.md` already names a Phomemo
M02 thermal printer as the existing print channel (`bin/catprint`),
already used for reports. Whether that same printer can produce a
spine-label-sized LCC label, or a dedicated label printer is needed, is
an open hardware question (see Blockers below) — the LCC-computation and
label-image-rendering code can be built and tested (render to PNG,
compare against a fixture) without settling that question, same PIL-render-
then-print pattern `crt-print.sh` already uses for reports.

## Roadmap

1. **Now (offline-safe, nightly-batch can start immediately): DONE,
   2026-07-21.** Built `bin/crt-book-game.py` + `tests/test_book_game.py`
   (20 cases, all green, registered in `tests/run_tests.sh`): ISBN lookup
   client (real Open Library call confirmed working — smoke-tested live
   against `9780141439518`, not just mocked), deterministic question
   templates (year/author-name/fiction-vs-nonfiction, with an
   always-available fallback question so the game never comes up empty),
   the Claude-batch prompt-building/response-parsing pair
   (`build_claude_batch_prompt`/`parse_claude_batch_response`, pure
   functions, no live Claude call wired yet — the CLI itself always uses
   the template path today, only recording which source the coin flip
   *would* have picked, since the actual `claude -p` invocation needs the
   same hands-on wiring as `crt-secretary.py`'s Claude-routing path),
   grading/logging (`grade_answer`/`log_training_row`, exact-ish per
   direction below), SQLite registry (`get_db`/`register_book`/`get_book`,
   cache-on-first-insert, confirmed a re-scan never overwrites), naive LCC
   heuristic (`compute_lcc`, keyword table, explicitly best-effort).
   `crt-book-game.py --isbn <n>` works standalone today for manual testing
   without any hardware. **Not yet done, deliberately out of scope for
   this pass:** the actual live Claude Code shell-out for the batch
   question path (needs the same `claude -p` wiring pattern as
   `crt-secretary.py`, and per "standalone first, merge later" below,
   shouldn't be built at the same time as hardware integration).
2. **Next (needs a live crt-vm session, hands-on):** scanner delivery
   is DONE via TWO paths now — `SCANNER.md`'s dexter-bridge (network,
   `[scan] <isbn>` into tmux) and, as of 2026-07-21, direct stdin
   reading in `crt-book-console.py` (the actual working path in
   practice, per the hands-on agent's live finding that raw scan
   keystrokes reach whichever window has focus regardless — see
   `.claude/FOCUS.md`'s "Stdin-scan pivot" entry). Grading is also
   automatic now (`crt-book-answer-listen.py`, watches `~/.crt/stt.log`).
   What's still needed: run the whole loop against a REAL physical scan
   and a real spoken answer (offline-verified only so far), human-verify
   the grading feels fair (false "you got it wrong" from bad STT is the
   failure mode to watch for, hence exact-ish-not-fuzzy grading), and put
   a human eye on `BOOK-GAME-STYLE.md`'s screen/color/art choices against
   the actual tube.
3. **Console placement: a new tmux window, DONE 2026-07-21.**
   `bin/crt-book-console.py` is wired into `crt-console.sh` as window
   `book` — tails `~/.crt/scanner.log` (already written unfiltered by
   `crt-scanner-feed.py`), looks up/registers each new ISBN-shaped line,
   and renders the centered question screen. Unconditional in
   `crt-console.sh` (not gated behind an env var like the `hook` window),
   since the scanner bridge itself is a standing systemd service now, not
   optional hardware. 10 new tests (`tests/test_book_console.py`), one
   real live-fetch smoke test against a fixture `scanner.log` (confirmed
   the whole idle→scan→question→idle-again cycle end to end).
   **Automatic spoken-answer grading, DONE 2026-07-21** (was manual-only
   above): `bin/crt-book-answer-listen.py`, a new tmux window
   (`bookanswer`), watches `~/.crt/stt.log` (already written by
   `crt-stt-solo.py` for every recognized utterance) and grades the next
   one against whatever book was scanned within
   `CRT_BOOK_ANSWER_WINDOW_SECS` (default 20s) automatically — reuses
   `grade_answer()`/`log_training_row()` unchanged, no new grading logic.
   "Pending question" is derived from `books.db`'s own `first_scanned`
   column (most-recently-registered book, if recent enough), not new
   shared state, so it can't drift out of sync with what actually got
   scanned. `crt-book-game.py --answer` still works standalone for manual
   testing/backfill. 13 new tests (`tests/test_book_answer_listen.py`).
   **Not yet eye-verified on the real
   tube** — same caveat as `BOOK-GAME-STYLE.md`'s own Status section.
4. **Stretch, now demoted:** label printer integration. **Resolved
   2026-07-21, Zach: skip it for v1.** The Phomemo M02 itself is known
   to work (already the report-printing channel, `bin/catprint`), but
   it's Bluetooth — likely the same class of VM-passthrough problem as
   the scanner's USB issue and the MIDI controller's USB issue, unverified
   either way. Rather than spend a hands-on session confirming/fixing a
   third passthrough path, **just display the computed LCC number on the
   CRT** for now (short text, fits this project's existing "CRT = short
   status only" convention from `SECRETARY.md`) instead of printing a
   label. Revisit physical labels once Bluetooth-through-VM is either
   confirmed working or solved the same way the scanner/STT bridge was
   (a dexter-side network relay) — not blocking anything above it.
   **Actually wired into the screen, 2026-07-21** (this decision was
   resolved back on the original vision day but never implemented until
   now — a real gap between decision and shipped feature):
   `crt-book-console.py`'s `render_scan_result()` now shows
   `Title (LCC)` in the question screen's title line when an LCC was
   computed, falling back to the plain title when it wasn't (in
   practice, often — Open Library's ISBN endpoint rarely includes
   `subjects`, that's mainly on the Works endpoint, so `compute_lcc`
   frequently has nothing to work with; confirmed live against a real
   scan). 2 new tests, full suite green.

## Blockers / open questions for a human

- **Barcode scanner bridge: RESOLVED and confirmed LIVE, 2026-07-21 —
  see `SCANNER.md` for the full build.** The dexter-side network-bridge
  path predicted below was exactly right: `bin/dexter-scanner-forward.ps1`
  (runs on dexter, Win32 RawInput API, filtered to this scanner's
  `HID\VID_0145&PID_0012`) POSTs each decoded barcode to a listener
  (runs on crt-vm, systemd-managed, survives
  reboot) over a new NAT port-forward (host 8993 → guest 8993), which
  delivers into the tmux Claude Code pane prefixed
  `[scan] <isbn>` — same channel STT transcriptions already use, just
  visibly tagged as a scan event, not a spoken sentence. **Confirmed
  working end-to-end with a real physical scan**, not just a synthetic
  POST. `crt-book-game.py`'s `parse_scan_line()` (added this pass)
  strips that `[scan] ` prefix and validates the ISBN shape, so the
  hands-on wiring step below is now "call `parse_scan_line()` then
  `crt-book-game.py --isbn <n>`," not a new integration to design.
  Superseded finding, kept below for history:
  <details><summary>original NOT-reaching-the-VM finding (2026-07-21, superseded)</summary>

  Identified the scanner on dexter's host USB list (`0145:0012`,
  "Unknown" manufacturer, confirmed by unplug/replug diff) and ran
  `VBoxManage controlvm crt-vm usbattach <uuid>` directly. The command
  returned **no error** (unlike the MIDI controller's explicit "busy
  with a previous request"), but: `VBoxManage list usbhost` afterward
  still showed the device `Current State: Busy`, never `Captured`: and
  `ls /dev/bus/usb/*/*` on the guest showed only the two root hubs, no
  new device. So the attach silently no-ops — same underlying failure
  class as the MIDI controller, just a quieter symptom.
  </details>
- **USB passthrough risk (MIDI controller, unconfirmed for anything
  else):** `HANDOFF.md`'s MIDI section documents `VBoxManage usbattach`
  failing ("busy with a previous request") for the Arturia MiniLab,
  root-caused to a stuck VBoxSVC host-proxy state, not yet cleared. Fix
  is a VBoxSVC restart on dexter (needs a human's direct OK, live VM
  depends on it) or a full dexter reboot — not attempted from here.
- **Reboot survival of the STT/meter pane — checked live 2026-07-21,
  did NOT reproduce.** Zach flagged a concern that the tmux pane carrying
  the audio meter might not spawn on reboot at all. Checked directly on
  `crt-vm` after this morning's 04:25 boot: `tmux list-windows -t claude`
  shows all 4 windows present (`bash`/claude, `mono`, `bridge-`, `stt`);
  `tmux capture-pane -t claude:stt -p` shows the meter live (`MIC
  [.|..] 0.8%`); `ps aux` confirms `crt-stt-solo.py` (pid 1118) running
  since 04:25, wired to `CRT_STT_SINK=claude`/`CRT_TMUX_PANE=0.0` as
  expected. So on this boot, the pipeline the book game depends on is
  intact — the 2026-07-20 fix (wiring the good layout directly into
  `crt-console.sh`) appears to be holding. Not proof it's fixed for
  every reboot (single data point), but no reproduction of the specific
  failure mode Zach was worried about. Re-check after any future reboot
  before assuming this is settled either way.
- **Long-term direction, explicitly parked (2026-07-21, Zach):** the real
  fix for reboot fragility isn't just "make the layout survive a reboot"
  — it's booting the VM into an **auto mode that lets Claude keep making
  ongoing modifications to the VM's own design**, specifically to reduce
  live API calls by replacing more of the STT-handling with on-site
  scripted logic over time (the same direction as `FOCUS.md`'s "Now
  (core STT)" long-term item: "replace gate-then-type-into-Claude with a
  real local text-handling service... escalates to Claude only when it
  doesn't know what to do"). Not being built now — parked alongside that
  existing long-term item, flagging here so it isn't lost and isn't
  conflated with the book game's own scope.
- **Label printing — resolved 2026-07-21, Zach: skip for v1.** Printer
  identity is settled (Phomemo M02, known-working, already the
  `bin/catprint` report channel) but it connects via Bluetooth, and
  Bluetooth-through-VM is unverified and likely hits the same class of
  passthrough problem as the scanner's USB path and the MIDI
  controller's USB path. Rather than debug a third passthrough route,
  v1 displays the computed LCC number on the CRT instead of printing a
  label (see Roadmap step 4, demoted from stretch-goal-now to
  later-revisit). Not blocking anything above it.
- **Book-metadata API choice:** Open Library's ISBN API needs no key and
  is fully offline-buildable-against (mockable); Google Books' has richer
  data but usage limits. Recommend starting with Open Library only,
  falling back to Google Books later if fact quality/coverage is
  insufficient for generating good multiple-choice questions — this is a
  build-time choice, not one that needs a human decision now.
- **LCC computation accuracy — resolved 2026-07-21, Zach: build a naive
  heuristic now, not a stub.** A small subject-keyword → LCC-range table
  (e.g. subject contains "fiction" → PS/PR, "history" → D, "science" →
  Q) computed from the Open Library lookup's subject headings, clearly
  labeled "best effort, not authoritative" wherever shown/printed — real
  subject→LCC assignment is a genuinely fuzzy library-science problem,
  this is explicitly not trying to solve that, just get the
  registry/label-printing pipeline wired end to end now.
- **Network egress — checked live 2026-07-21, confirmed working.** This
  disposable-clone environment successfully reached
  `openlibrary.org` (`curl` got a real `302`, not a timeout/DNS
  failure) — the offline-safe build can be verified against the real
  API, not only mocks, though tests should still mock by default for
  determinism/speed and use a real call only as an occasional smoke
  check.
