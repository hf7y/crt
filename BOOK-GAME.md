# Book Game: a training-data game for crt-vm (2026-07-21, vision)

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
   Ray or Roy?", "Fiction or nonfiction?"). One option is correct.
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

1. **Now (offline-safe, nightly-batch can start immediately):** ISBN
   lookup client, question generator, grading/logging, SQLite registry,
   LCC call-number computation — each with `tests/` coverage, each
   wired behind a CLI (`crt-book-game.py --isbn <n>` for manual testing
   without hardware) before any hardware integration.
2. **Next (needs a live crt-vm session, hands-on):** wire the real
   scanner (plug in, confirm HID passthrough works exactly like a
   keyboard — should need zero new driver work per how these scanners
   work, but unverified on this specific VM/USB-passthrough setup given
   the MIDI controller's `VBoxManage usbattach` troubles, see Blockers),
   run the loop against the real mic pipeline, human-verify the
   grading feels fair (this is a game — false "you got it wrong" from
   bad STT is the failure mode to watch for specifically, hence the
   exact-ish-not-fuzzy grading choice needing a real ear on it early).
3. **Then:** decide standalone-vs-integrated placement in the console
   (new tmux window? a secretary playbook? both?) once the standalone
   version is proven fun and correct.
4. **Stretch:** label printer integration once the printer question
   (below) is answered.

## Blockers / open questions for a human

- **Barcode scanner almost certainly won't reach the VM via direct USB
  passthrough (2026-07-21, Zach).** Same class of problem as the MIDI
  controller's `VBoxManage usbattach` trouble below, but Zach's read is
  it's the known dexter→VM USB passthrough issue specifically, not just
  a one-off stuck-service state — expect it to fail the same way. The
  scanner will need to go over **the same path STT audio already uses**
  (dexter-side capture → network/HTTP bridge into the guest, like
  `dexter-whisper-server.py` for audio) rather than raw USB passthrough.
  Concretely: a small listener on dexter reads the scanner's HID/serial
  output natively and posts scanned ISBNs to `crt-book-game.py` on the
  VM over the network, mirroring `CRT_WHISPER_SERVER`'s shape. This is
  now the assumed integration path for the hands-on phase, not
  `VBoxManage usbattach` — the USB-passthrough item below is kept for
  the MIDI case specifically, since it may still be worth clearing for
  that controller even though the scanner won't use the same route.
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
- **Which printer for LCC labels, and can it even do label-sized
  output:** does the existing Phomemo M02 (`bin/catprint`, currently used
  for report printing) support a small enough label format for a book
  spine, or does this need a second, dedicated label printer? Needs a
  human decision once the core game works — not blocking anything above
  it.
- **Book-metadata API choice:** Open Library's ISBN API needs no key and
  is fully offline-buildable-against (mockable); Google Books' has richer
  data but usage limits. Recommend starting with Open Library only,
  falling back to Google Books later if fact quality/coverage is
  insufficient for generating good multiple-choice questions — this is a
  build-time choice, not one that needs a human decision now.
- **LCC computation accuracy:** the Library of Congress Classification
  outline is public, but assigning a *real* correct LCC number from raw
  ISBN-lookup metadata (subject headings, not a pre-assigned LCC field)
  is a genuinely fuzzy classification problem, not a lookup — early
  versions should treat the computed LCC as a best-effort label, not an
  authoritative library-science claim, and this should be stated
  wherever the label is shown or printed.
