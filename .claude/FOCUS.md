# crt — focus & backlog

- **2026-07-20 15:57 (via `scheduler -i`):** vision: crt off, handset on killswitch hookswitch. handset picked up = noise in line. lightweight watcher tracks mic signal, no AI API yet. handset pick up, IR beam monitor on, sidetone in earpiece. user speaks command in natural language, earpiece beeps expressively in response based on keyword type filter that directs a search tree. users voice shows as flickering line on crt (stt at bottom of screen, right aligned, line length based on amplitude, visual decay, eventually predictive text auto fills in words, or lighter weight stt with shorter window drops words that later get replaced by better stt. tunable afterglow that lets last recorded line persist for a few seconds for auditing. words grey out from left to right. language tree does its best to navigate without API calls, calls out to API when unsure, little light in the corner indicates claude has been requested. claude comes in and takes over the bot voice (user never feels it). program is always recording stt results (eventually voice when we merge vm and windows halves) and generating more accurate handling of interactions. games and idle bait are important ways of requesting specific sonic information in a structured way that informs the voice detection model. we never feel it when claude comes in to take over, other than the color change. calls to claude leave residue for future refinement automatically but the token usage of claude calls should be minimized by default and tunable.

**Heads-up (2026-07-20, from scheduler's own repo) — check scheduler's
current state before building against old assumptions.** A significant
scheduler redesign session happened today: the `.claude/**` permission
gate crt's own `MORNING-REPORT-PRESENTATION.md` work ran into is now
root-caused and fixed (files move to a top-level `.scheduler/` dir,
outside `.claude/`); `bin/morning-report.sh`/`DIGEST.md` — the interface
`crt-present-morning-report.py` parses — is very likely getting retired
in favor of `bin/scheduler` (a real, already-working CLI: `scheduler`,
`scheduler -b/-f/-q/-r`), not just fixed for the hang bug crt reported.
Before doing more work on the morning-report presenter specifically,
read scheduler's own `.scheduler/FOCUS.md` (the "Vision", "Consolidation
roadmap", and blockers-aggregation sections) to see whether the shape
being parsed is still the right target.

**Current focus: the core STT pipeline** (see "Now (core STT, blocked on
VM)" below) — but every item there needs a live `crt-vm` session, which an
unattended batch run doesn't have. See `../HANDOFF.md` for full state and
access.

**2026-07-20: all 8 offline-safe items below are DONE** (opt-in secretary
wiring, calibration-margin consumption, glissando earcons, ANSI colors,
TTS prosody, sideband wiring, calibrate playbook, fallthrough logging —
126 offline checks green, `tests/run_tests.sh`). Kept below for the
record/links; nothing left in this section for an unattended pass to
pick up until either a new offline-safe batch is registered here, or VM
access unblocks the STT section.

## Book Game — structured STT training-data game (2026-07-21, vision session)

**End-goal statement (2026-07-21, Zach) — the whole point of this
subsystem, keep every future piece pointed at this:** a voice-interactive
scanner system that idle-baits someone into picking up a book and
scanning it, then entices them to speak trivia into the mic that's used
for training the voice (STT). Idle-bait → scan → question → spoken
answer → STT training log is one continuous funnel, not four separate
features — judge any future addition by whether it strengthens a step in
that funnel. **Division of labor going forward**: this account (the
unattended nightly-batch tier) develops continuously at a controlled
pace; a separate hands-on agent watches this work, syncs it to crt-vm,
does simple dexter/crt-vm-side tasks, and reports back on its own
recurring loop (see the "2026-07-21 late session" pivot below for an
example of exactly that kind of hands-on finding this account can't
produce alone).

Full vision, roadmap, and open questions: `../BOOK-GAME.md`. Direct instance
of this file's own 2026-07-20 15:57 vision line ("games and idle bait are
important ways of requesting specific sonic information in a structured
way that informs the voice detection model") — scan a book's ISBN barcode,
ask a 2-option multiple-choice question about it, grade the spoken answer
against the two known option strings, log every (expected, heard) mismatch
as labeled STT training data, register the book locally. Stretch: print an
LCC label per book via the existing Phomemo/`catprint` channel or a
dedicated label printer (open question, see BOOK-GAME.md).

**Offline-safe slice: DONE, 2026-07-21.** `bin/crt-book-game.py` +
`tests/test_book_game.py` (40 cases, all green in `tests/run_tests.sh`,
plus a live smoke-test against the real Open Library API). Covers ISBN
lookup, question templates + Claude-batch prompt/parse (pure functions,
no live `claude -p` shell-out wired yet), grading/logging, SQLite
registry, best-effort LCC, screen layout/centering, ASCII art, CRT-safe
color palette, non-API idle-bait quotes (`bin/crt-book-idle-bait.py` +
`tests/test_book_idle_bait.py`), and `parse_scan_line()` bridging
`bin/crt-scanner-feed.py`'s `[scan] <isbn>` delivery convention
(SCANNER.md) to this CLI's `--isbn`/`--scan-line` args. Full detail in
`../BOOK-GAME.md`'s Roadmap step 1 and `../BOOK-GAME-STYLE.md`.
**Now wired into `crt-console.sh` as its own tmux window (`book`),
2026-07-21** — `bin/crt-book-console.py` tails `~/.crt/scanner.log` and
renders the question screen for each new scan. 10 more tests
(`tests/test_book_console.py`), full suite green. Not yet wired into
`crt-secretary.py`'s playbook dispatcher — that's still a separate,
not-yet-built step.

**Spoken-answer grading now automatic, 2026-07-21** (closes the last
manual-only link in the funnel): new `bookanswer` tmux window,
`bin/crt-book-answer-listen.py`, watches `~/.crt/stt.log` and grades the
next recognized utterance against whatever book was scanned within
`CRT_BOOK_ANSWER_WINDOW_SECS` (default 20s), reusing
`grade_answer()`/`log_training_row()` unchanged — "pending question" is
derived from `books.db`'s own `first_scanned` column, not new shared
state. Built as its own file rather than editing `crt-book-console.py`/
`crt-book-game.py` directly, since both were mid-live-debug elsewhere the
same session (missing `random` import, `quote`-column migration) —
avoided colliding with that work.

**Result announcement added, 2026-07-21**: grading used to only print
debug text to the `bookanswer` pane. `format_result_line()` now composes
an actual game-show-host announcement in `BOOK-GAME-STYLE.md`'s register
(content/settled "got it!" for correct, clipped "nope, it was X" for
wrong, neutral "logged your answer" for ungradeable fallback questions,
never gloating or sad either way) and appends it to `~/.crt/thoughts.log`
— same channel `crt-monologue.sh` already tails, so a graded answer now
actually shows up on screen instead of only in a background pane's debug
log. 6 more tests, 19 total (`tests/test_book_answer_listen.py`), full
suite green.

**Idle-bait rebuilt around the actual end-goal, 2026-07-21 (see above)**:
`bin/crt-book-idle-bait.py` and `crt-book-console.py`'s idle screen now
mix enticement lines (invite a NEW scan — `pick_entice_line()`,
`ENTICE_LINES`) with quote lines (celebrate a book already scanned) —
previously an empty `books.db` meant idle-bait silently did nothing at
all, now it always shows an enticement line. Also added real per-book
quotes via a Wikiquote webscrape (`scrape_quote()`, not an AI call,
cached once per book) and 3 kawaii ASCII art entries. Full detail in
`../BOOK-GAME-STYLE.md`'s "Idle-bait: two registers" section. 12 more
tests, full suite green.

### Stdin-scan pivot: DONE 2026-07-21 (was "NEXT (late session)")

Both steps of the hands-on agent's confirmed-live plan are now built:
1. **`bin/crt-book-console.py` reads its own stdin.** A background thread
   (`stdin_reader`) iterates `sys.stdin` (terminal cooked mode already
   buffers a scan's fast keystrokes until Enter, same as a human typing)
   and pushes lines onto a queue the main loop drains non-blockingly
   alongside the existing `scanner.log` tail — `parse_stdin_scan_line()`
   validates ISBN shape (no tab-prefix to strip, unlike `scanner.log`'s
   format), then reuses `handle_scan()` unchanged. Stdin is the primary
   path in practice now; `scanner.log` stays wired as a fallback in case
   the dexter bridge is ever fixed.
2. **`bin/crt-console.sh` makes `book` the boot-default window** instead
   of `claude` (window 0) — the manual `tmux select-window` the hands-on
   agent did live now survives a respawn/reboot. `claude` stays one
   `prefix+0` away.

**Verified**: a real subprocess smoke test (bare ISBN piped to stdin,
real Open Library fetch) rendered the correct question screen end to
end. `dexter-scanner-forward.ps1` + the scanner NAT port-forward +
`crt-scanner-feed.py`'s systemd service are now "nice to have, not
load-bearing" for book-scanning, exactly as planned. 4 new tests
(`tests/test_book_console.py`), full suite green. **Still needs an
actual physical scan on the real tube** to fully close this out — this
session already got burned once by an unverified "confirmed working"
claim on the dexter-side path, so treat this as offline-verified only
until a human watches a real scan render correctly.

Original context/writeup (dexter dead-end root cause) kept in
`../SCANNER.md`'s "2026-07-21 late session" section for history.

### Book Game training-data stats, DONE 2026-07-21

The end-goal (see this section's opening statement) is STT training
data — until now that data just sat in `~/.crt/book-game-training.jsonl`
with no way to see progress without reading the raw file by hand. New
`bin/crt-book-game-stats.py` (zero Claude calls, pure local reads of
`books.db` + the training log) surfaces book count, question-source
mix, and — given top billing over trivia correctness, since it's the
actual point — **STT accuracy**: how often what was heard matched what
was expected, plus every logged mismatch (the literal training
artifact). `screen`/`print-all` modes match
`crt-present-morning-report.py`'s existing convention. Also wired into
`crt-secretary.py` as a new `book_game_stats` playbook ("how's the book
game going", "trivia stats") so it's reachable by voice the same
locally-answered way `status`/`morning_report` already are. 14 + 3 new
tests (`tests/test_book_game_stats.py`, `TestBookGameStatsPlaybook`),
full suite green.

**Training data made actionable, 2026-07-21**: displaying mismatches
wasn't enough — `crt-book-game-stats.py export-fixups` now converts
repeated (expected, heard) mismatches into candidate
`bin/stt-fixups.json` entries, the exact shape that file already uses
(`STT-MECHANISM.md`'s garble taxonomy), always marked `confidence:
candidate` (never `confirmed` — matches that file's own bar, only a
human calibration session earns `confirmed`). Only surfaces a pair once
it's recurred at least twice (tunable), since a one-off mismatch could
just be noise. This is the actual "improve STT inference over time"
loop CLAUDE.md names as this console's top priority, closed end to end:
scan → question → spoken answer → logged mismatch → candidate fixup a
human can review and copy straight into the real file. 5 more tests,
24 total, full suite green.

**Full-funnel offline integration test added, 2026-07-21**:
`tests/test_book_game_integration.py` runs `crt-book-game.py` →
`crt-book-console.py` → `crt-book-answer-listen.py` →
`crt-book-game-stats.py` together against one shared `books.db` +
training log — real registration, real grading, real announcement
rendering, real re-scan cache-hit check, and a repeated-mismatch →
candidate-fixup check, all in one scenario. Distinct from every
individual file's own unit tests (which each mock their neighbors) —
this catches data-shape mismatches between files that grew across many
separate passes, before they'd ever surface live. All 3 scenarios passed
on first write, confirming the pieces built independently across today's
passes do actually compose correctly.

**Real crash bug found and fixed, 2026-07-21 — CONFIRMED LIVE, not
theoretical.** `fetch_book_metadata()` raises on any ISBN Open Library
doesn't recognize (confirmed live: a real `curl` against
`openlibrary.org/isbn/0000000000.json` returns a genuine `404`) or on a
network failure — and until this fix, **nothing caught it anywhere**.
Since the whole point of this feature is inviting someone to scan "any
book nearby," this was guaranteed to crash the `book` window (now the
boot-default tmux window) on a large fraction of real scans — out-of-
print books, non-ISBN barcodes, a network hiccup — not a rare edge case.
Same failure class as the earlier missing-`random`-import crash, just
certain to recur constantly instead of being a one-off. Fixed:
`crt-book-console.py`'s `handle_scan()` now raises a distinct
`ScanLookupFailed` (not a bare re-raise) that `main()` catches and shows
via a new `render_scan_error()` screen ("couldn't find that book, try
another!", clipped/`COLOR_WRONG` register) instead of crashing;
`crt-book-game.py`'s CLI degrades to a clear message instead of a raw
traceback. **Verified live against the real Open Library API** (not just
mocked): both the console window and the CLI handled ISBN `0000000000`
cleanly, no crash, no traceback. 6 new tests, full suite green.

**Next offline-safe batch pickup (registered 2026-07-21, not yet
built): real webscrape quotes + kawaii ASCII art.** Idle-bait quotes
currently only use Open Library's `first_sentence` field (rarely
populated) plus a 5-entry static fallback pool (`bin/crt-book-idle-bait.py`,
`BOOK-GAME-STYLE.md`) — Zach wants an actual per-book quote pulled by
webscrape (explicitly NOT an AI/Claude call, just literal scraped text).
Confirmed live from this account's sandbox: Wikiquote's MediaWiki API
(`https://en.wikiquote.org/w/api.php?action=query&list=search&srsearch=<title>`
then `...&prop=revisions&rvprop=content&rvslots=main&titles=<page>`) is
reachable and its wikitext is straightforwardly parseable — top-level
`* text` lines are real quotes, `** text` lines are attributions/sources
to skip, `[[link|display]]`/`'''bold'''`/`''italic''` markup needs
stripping. Build a `scrape_quote(title, fetcher=None)` pure-ish function
in `crt-book-game.py` (injectable fetcher for tests, same pattern as
`fetch_book_metadata`), called once at fresh-registration time (not at
idle-bait read time, so idle-bait itself stays a pure local read) and
cached into a new `quote` column in `books.db` — never re-scraped on a
re-scan, same cache-once philosophy as questions/LCC. Wire the fallback
chain as: cached scraped quote → `extract_quote()`'s `first_sentence` →
the static pool, in that priority order. Wrap the whole scrape in a
broad try/except (network flake, no Wikiquote page, empty parse all
possible) so a slow/unreachable Wikiquote can never block or crash a
scan — falls through to the existing chain instead. Also add 2-3
kawaii/kaomoji-style entries to `ASCII_ART` (in the same voice as
`crt-idle-bait.sh`'s existing `(=^-^=)`-style faces, not the current
plain line-art `book`/`cat_reading`/`bookworm`/`shelf` set) — hand-authored,
not scraped, per the ASCII-art library's existing "not machine-fetched"
convention. Full offline-buildable and testable (mock the Wikiquote
fetcher in tests, same as Open Library's), no hands-on crt-vm session
needed for this piece.

**Scanner hardware bridge is no longer a blocker** — `SCANNER.md`
(built by a separate hands-on crt-vm/dexter session, 2026-07-21) has the
dexter→crt-vm scanner forward live and systemd-persistent, and the new
`book` tmux window above already consumes it directly. Remaining
hands-on work (BOOK-GAME.md roadmap step 2): run against the real mic,
and eyeball `BOOK-GAME-STYLE.md`'s screen/color/art choices on the
actual tube. Also still open (not hardware, just not built this pass):
the live `claude -p` shell-out for batch question generation, and
grading wired into a live session instead of the manual CLI.

## Cross-project ask: locate prior demucs work on dexter (2026-07-20)

`wtul` (the CD-ripper project) needs Demucs for ROADMAP #5 (instrumental
intro/outro detection) and Zach says he already tried installing/running
Demucs on dexter once before, with leftover files somewhere on that
machine. This project runs on dexter/crt-vm and is the thing already
reaching dexter over the network (see `dexter-whisper-server.py`), so it's
the natural place to leave this note for whoever/whatever next has hands
or a session on dexter.
%%ACTION next time there's a live session on dexter (not the isolated
nightly-batch clone — this needs the real machine), look for prior Demucs
install/model-download artifacts (check pip/conda envs, `~/.cache`,
anywhere resembling a `demucs` venv or downloaded checkpoints). Report
findings back — either the path to reuse, or confirmation there's nothing
to reuse — to `wtul`'s `ROADMAP.md` #5 / `.claude/QUESTIONS.md` (the
cross-project scheduler `BLOCKERS.md` has the `## wtul` heading if a
quicker landing spot is wanted instead).

## DONE (offline-safe, no VM/dexter needed) — registered 2026-07-20, completed 2026-07-20

Every item here is buildable and testable with `tests/run_tests.sh` alone
— no VM, no dexter, no real audio hardware. Each MUST land with its own
test coverage added to `tests/`, and any behavior change to an existing
default pipeline (stt-feed.sh, crt-stt-solo.py) MUST be opt-in via an env
flag, default off, exactly like `CRT_PREDICT_FLASH` already is — none of
this should change what the live console does today until a human can
watch it run. Do NOT claim anything "sounds good," "feels right," or is
hardware-verified — that bar still needs a real ear/eye, see the
acceptance-bar note in `.claude/commands/nightly-batch.md`.

1. **Wire `crt-secretary.py` into `stt-feed.sh`**, opt-in
   (`CRT_SECRETARY=1`, default off — the raw send-keys path stays the
   default). Test with a mocked tmux, same pattern as
   `tests/test_secretary.py`. See `SECRETARY.md`/`SUPERVISOR.md`.
2. **Consume the calibration margin**: `crt-pager.py`/`crt-monologue.sh`
   don't read `~/.crt/display.conf` yet — subtract the saved margins from
   the auto-detected WIDTH/HEIGHT. See `DISPLAY-CALIBRATION.md`'s "not
   done this session" note.
3. **Extend `crt-earcon.sh`'s pitch contours** — most registers are still
   plain note sequences, not the glissando/sweep shapes `oops` already
   uses. See `EXPRESSIVE-TONE.md`'s "explicitly not doing (yet)" list.
4. **ANSI color-per-register** in `crt-idle-teaser.sh`/`crt-monologue.sh`
   output — the color dimension `EXPRESSIVE-TONE.md` named but didn't
   reach. `CLAUDE.md` explicitly grants ANSI control of the screen.
5. **Per-call TTS prosody overrides** in `crt-tts.py` — pitch/rate/volume
   currently only come from flat `tts.conf`/env config, not per-call, so
   the register taxonomy can't actually vary spoken delivery yet. See
   `EXPRESSIVE-TONE.md`.
6. **Wire sideband state transitions**, opt-in — `crt-stt-solo.py` (VAD
   start/stop -> listening/idle), `crt-secretary.py`/`crt-tts.py`/
   `crt-earcon.sh` (mute-duck around their own playback via
   `~/.crt/sideband.mute`). See `SIDEBAND.md`'s "not done this session."
7. **A `calibrate` playbook** in `crt-secretary.py` — voice trigger runs
   `crt-calibrate-display.py show`. Named as the natural next playbook in
   `SUPERVISOR.md`.
8. **Fallthrough-logging** in the supervisor — log any request that
   matches no playbook (to a file, not acted on) so a future session can
   see which requests keep escalating to Claude and are worth a new
   playbook. `SUPERVISOR.md`'s open item.

Stop-by-report-time applies as usual (see nightly-batch.md step 3's
budget). If only some of these fit in one pass, do them in the order
listed — earlier items unblock/inform later ones (2 and 7 are related;
6 depends on nothing else here).

## Now (core STT)

- **2026-07-20: Approach B (single-reader `crt-stt-solo.py`) is now live and
  promoted into `bin/crt-console.sh`'s actual boot default** — see
  `AUDIO-DEBUG.md` and `HANDOFF.md`. The dsnoop-staleness class of bug (A/C/D
  below) is now moot for the default boot path since there's only one reader;
  those approaches stay documented in `AUDIO-DEBUG.md` in case `stt-feed.sh`'s
  debug/secretary modes need them later, but aren't the active priority.
- Ongoing calibration: `CRT_VAD_THRESHOLD`, Windows mic boost, normalization.
  **Needs the VM** — not urgent, current defaults are working.

### STT gate — don't call Claude on room noise/ambient conversation (2026-07-20, Zach)

Right now every utterance `crt-stt-solo.py`'s VAD cuts gets typed straight
into the Claude pane — **every** clip that clears the VAD threshold and
produces non-empty whisper text becomes a live Claude Code turn, including
room chatter never meant for the console (`CLAUDE.md`'s whole premise is a
noisy room). That's a real cost/privacy problem, not just noise: the console
is currently "always listening AND always escalating."

**Zach's direction (2026-07-20):** build a simple gate now; the long-term
target is bigger than a gate:
1. **Near-term (this item): a simple gate.** Before an utterance reaches
   Claude, decide locally whether it's actually addressed to the console.
   Candidates (pick one or layer them, this is a real design decision for
   whoever picks this up, not a spec):
   - **Wake word**: require "claude" (or another trigger word) to appear in
     the utterance before typing it in; otherwise just log to `stt.log`/
     `thoughts.log` and drop it. `bin/stt-fixups.json` already has a
     confirmed mis-hear entry for this exact word ("slide" → "claude"),
     which a wake-word gate makes load-bearing rather than cosmetic — get
     the fixup lookup wired into whatever does the gating.
   - Keyword/intent filter (per the very first FOCUS.md vision entry at the
     top of this file, 2026-07-20 15:57: "language tree does its best to
     navigate without API calls, calls out to API when unsure").
   All of the *logic* here (string/keyword matching against a transcribed
   utterance) is offline-testable — no VM needed to build and unit-test the
   gate itself, only to verify it live against real room noise once written.
2. **Long-term (do NOT build this now, just keep the shape in mind so the
   near-term gate doesn't paint it into a corner)**: replace "gate then type
   into Claude" with a real local text-handling service — non-AI, handles
   known commands/patterns directly, and *escalates* to Claude only when it
   doesn't know what to do. This is a bigger rewrite of the stt→claude
   pipeline (`crt-stt-solo.py`'s `CRT_STT_SINK=claude` path), not a
   follow-up to the gate — flagging so the near-term gate is built as a
   clean layer that a future service can slot in front of, not a
   Claude-specific hack.

**Parked for the nightly batch** — this is Zach's explicit call ("we'll park
that for the nightly runs"), not urgent for this session.

## Deferred (not in current focus — do not pull these into an STT session)

**Moved 2026-07-20**: the hands-on-hardware items that used to live here
(MIDI controller, physical hookswitch, OctoPrint, Benchy print, USB
phone-interface module, the VM-hardware-check install) now live in the
scheduler's cross-project `BLOCKERS.md`, under `## crt` — that file is the
one-glance human-owned surface across every project; this one stays
scoped to code-shaped backlog. Still deliberately **not** in current
focus, still branch around anything needing hands on hardware or a live
VM if it resurfaces here by mistake.

1. **Stretch: video-call wrapper** (Zoom/WhatsApp) over the handset/CRT —
   not a blocker (nothing needed from a human to start), just genuinely
   unstarted backlog, lowest priority.

## Secretary reframing (2026-07-19) — see SECRETARY.md
The real goal is a phone-secretary service, not a raw STT->Claude terminal.
Printer = long output, CRT = short status + slow-scroll (`bin/crt-pager.py`,
built), TTS = spoken confirmation through the phone (`bin/crt-tts.py` +
`bin/crt-tts-calibrate.py`, built + espeak-ng deployed to crt-vm), TV
announcements for Chris rate-limited to 1/15min (`bin/crt-announce.sh`, code
done, cross-VM-boundary bridge to actually reach the TV output NOT built --
see AUDIO-ROUTING.md). `bin/crt-stt-speakback.sh` runs STT in debug mode
(stdout, NOT wired to Claude) and speaks "heard: ..." back through the phone
so a person can debug the mic by ear -- running live on crt-vm's `stt` window
as of 2026-07-19. The actual secretary wrapper (structured request -> Claude
-> route response to printer/CRT/TTS) is still design-only, next concrete step.

## MIDI passthrough — parked, see PARKING-LOT.md (2026-07-20)
Root cause of the original failure is known (fixed) but `VBoxManage
usbattach` still fails on a stuck VBoxSVC host-proxy state, needs a
process restart on dexter that wants a human's direct OK first. Full
status, next step, and portability direction moved to
`PARKING-LOT.md`'s "MIDI controller pass-through" section — not on the
critical path for the core voice console, don't pull it back into an
unattended batch's scope.

## faster-whisper network service on dexter (2026-07-19, DONE, live)
`bin/dexter-whisper-server.py` runs faster-whisper natively on dexter's Ryzen
(port 8991, `/health` + `/transcribe`) so transcription isn't CPU-capped by
the VM. `crt-stt-solo.py` uses it when `CRT_WHISPER_SERVER=http://192.168.0.22:8991/transcribe`
is set — verified working live. Not auto-starting yet (manual
`Start-Process` on dexter); add a Scheduled Task next. See project memory for
the VPN/huggingface.co gotcha and how the model got there.

## Ring/pickup detection (2026-07-19, smoke-tested)
`bin/crt-ring.sh <n>` rings the phone via `crt-stt-solo.py` (the sole mic
reader) — warble tone in bursts, checks for voice only in the silent gaps
(avoids the tone false-triggering), stops on pickup, prints a timeout
message on the active screen if unanswered. No physical hookswitch yet, so
"pickup" is inferred from voice activity alone.

## Inner monologue / on-screen narration (2026-07-19, DONE, live)
`bin/crt-think.sh "text"` appends a timestamped line to `~/.crt/thoughts.log`;
`bin/crt-monologue.sh` tails it on-screen, word-wrapped, in first person as
the machine narrating itself ("i'm a crt, i have a handset..."). This is now
the CRT's active tmux window (STT moved to a background window, still
running/speaking, just not what's displayed). **Ongoing practice going
forward: narrate real work into this log in-character as it happens** (via
`crt-think.sh` over SSH) rather than only reporting after the fact — it
doubles as a durable append-only context record for later sessions.

## Offline test suite now exists (2026-07-19)
`tests/run_tests.sh` — shell syntax checks, `crt-pager.py`/`crt-monologue.sh`
width logic, `crt-predict.py` model logic. Zero VM/hardware needed. Any
future nightly-batch pass should run this before claiming a code-shaped
change "done" — it's real regression coverage now, not just an acceptance-
bar reminder.

## Idle-bait / beeps / sidetone / philosophy design pass (2026-07-19)
Design session, no VM access. Full detail in `.claude/SESSION-STATE.md`
(read that first next session) and the new top-level docs it lists
(`IDLE-BAIT.md`, `SIDETONE.md`, `PHILOSOPHY.md`, `RFP-GALLERY.md`,
`RFP-PAYPHONE.md`, `cad/CAD-BACKLOG.md`). New scripts, all code-shaped and
therefore fair game for an unattended nightly pass to extend/harden
(but NOT to mark "verified" — none of this has touched real audio
hardware yet, see the acceptance-bar note in `.claude/commands/
nightly-batch.md`):
- `bin/crt-earcon.sh`, `bin/crt-report.sh`, `bin/crt-idle-teaser.sh` — new,
  untested by ear/against live traffic. Safe unattended work: dry-run them
  (syntax, obvious logic bugs), NOT claiming they sound good or that the
  teaser cadence feels right — those need a human on the handset.
- `bin/crt-announce.sh` — bugfixed (stale TV device string). Low-risk to
  re-verify against `crt-tts.py`'s current `DEXTER_DEVICES` if that file
  changes again.
- Two open questions logged in `.claude/QUESTIONS.md` need Chris, not a
  guess: handset audio guest-vs-host routing (blocks sidetone), and
  idle-bait quiet hours.

## Parking lot: deep end-state vision — see PARKING-LOT.md
RF power-on-TV-when-handset-lifts, HDMI-to-RF multi-channel personas, hidden
transcription (blinking cursor only), predictive-typing-then-overwrite
aesthetic, two core jobs (morning reports + media playback), start on
dexter/Ryzen natively while the Compute Stick waits on a DAC. Not being
built yet — captured so the direction survives.

## Compute stick (still blocked, physical)
No progress possible remotely -- flashing/booting the actual Intel Compute
Stick STK1AW32SC needs hands on the physical device. The Ubuntu Server ISO
noted as "downloaded on mandark" in a prior session's scratchpad could not be
found this session (scratchpad from that session no longer exists) -- if
still needed, redownload before the next hands-on session.

## Autonomous overnight batch (enabled 2026-07-19)

crt is now a git repo pushed to a LOCAL bare remote (`~/git-remotes/crt.git`),
and registered with the scheduler's Tier 2 batch (`schedule/crt.conf`), 3
passes/night (01:45/03:45/05:45), 30-day auto-sunset. Each run reads this file
+ `AUDIO-DEBUG.md` and advances the code-shaped backlog (audio approaches, STT
watchdog/single-reader, USB firmware, video wrapper), branching around anything
physical. Reports land in `~/reports/crt/`. A GitHub mirror is optional later
(deploy key `~/.ssh/crt_deploy_key` is ready; swap `REPO_URL` in the conf).
