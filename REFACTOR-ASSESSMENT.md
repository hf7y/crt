# Refactor assessment — 2026-07-23

Engineering pass over the whole repo, companion to
`ARCHITECTURE-REVIEW-2026-07-23.md` (that doc asks "is the shape right?";
this one is a concrete cleanup backlog). Every item tagged **[offline]**
(a nightly-batch tier can do it unattended, no hardware) or **[live]**
(needs potato/mic/audio to verify). Cite-first, terse.

---

## 1. Dead / legacy code from the dexter / crt-vm era

potato (bare-metal Pi) has replaced the Windows-host + VirtualBox combo.
These files/paths are from that era and no longer describe reality.

**Safe to delete (nothing live imports them):**
- `bin/dexter-whisper-server.py` — superseded by `mandark-whisper-server.py`
  (same protocol, port 8991). Header hardcodes a `C:\Users\Zach` model path.
- `bin/dexter-audio-server.py` — the host-side `:8992/play` sink. No live
  script can reach it; potato routes audio to local ALSA now.
- `systemd/crt-vm-hardware-check.{service,timer}`, `systemd/crt-vm-watchdog.
  {service,timer}` — VM-lifecycle units (one references `VBoxManage`-style
  guest assumptions). potato uses `crt-console.sh` autologin + a different
  durability story.
- `bin/crt-sync-vm.sh`, `bin/crt-sync-vm-reports.sh` — two-way sync to the
  VM's non-git `~/crt`. potato is hand-copied too, but these encode VM host
  names / one-directional-to-VM policy that no longer holds.
- `bin/crt-vm-hardware-check.sh`, `bin/crt-vm-watchdog.sh` — VM-specific.
  The hardware-check logic is worth *porting* (mechanical presence checks
  are still useful on potato), but as-is it's crt-vm-shaped.

**Keep but fix the dexter assumption (live code with a stale default):**
- `bin/crt-tts.py:41` — `DEXTER_URL` default `http://192.168.0.22:8992/play`
  and `DEXTER_DEVICES=("tv","handset")` (`crt-tts.py:127-138`). When
  `--device tv|handset` is passed this POSTs to a server that does not exist
  on potato → silent failure. This is the *exact* class of bug that hid the
  earcon breakage (SESSION-STATE, "silent no-op"). Repoint to local ALSA
  like `crt-earcon.sh` already was, or gate the dexter path behind an
  explicit `CRT_AUDIO_OUT_URL` being set.
- `bin/crt-announce.sh:9,20` — same dexter `tv` device-name assumption.
- `bin/crt-scanner-feed.py` — header (lines 6-7, 26) still describes the
  dexter→crt-vm NAT forward. Scanner may still be wanted; the *doc* is
  legacy and it collides on port 8993 (see §2).

**Do not delete:** `crt-wake-pool.py` / `crt-wake-judge.py` /
`WAKE-TUNING-STATE.md` originate from the crt-vm era but are the
still-wanted wake-judge system (ARCH-REVIEW problem 1). Migrated unevenly,
not dead.

---

## 2. Config sprawl / magic constants (no single source of truth)

The recurring silent-breakage pattern in ARCH-REVIEW problem 3 is downstream
of this: the same value is retyped in shell, Python, and systemd, so a
change in one place rots the others.

- **Port 8993** hardcoded in `bin/crt-remote-claude-bridge.py:65`,
  `bin/setup-mandark-remote-claude-persistence.sh:31,48`, and
  `bin/crt-console.sh:144`. **Collision:** `bin/crt-scanner-feed.py:32`
  *also* binds 8993 (barcode scanner) with a different meaning — if both
  ever run, they fight. At minimum give the scanner its own port.
- **plughw device indices** scattered with inconsistent defaults:
  capture is `plughw:1,0` in `crt-console.sh:144` / `crt-earcon-loopback-
  test.py` but `plughw:0,0` (the known-broken index, SESSION-STATE) is still
  the default in `crt-stt-solo.py:120`, `crt-stt-stream.py:53`,
  `stt-feed.sh:49`, `crt-capture-watchdog.sh:34`, `crt-audio-doctor.sh:23`,
  `crt-stt-stream-view.sh:19`. TV=`plughw:2,0`, handset=`plughw:1,0` retyped
  in `crt-earcon.sh:212-213` and the loopback test. Any tool run without the
  `crt-console.sh` env override silently uses the wrong/dead device.
- **Whisper URL** `http://192.168.0.27:8991/transcribe` in
  `crt-console.sh:144`; other files carry `192.168.0.22` / `192.168.0.32`
  in headers as examples (`crt-stt-solo.py:169`, `crt-stt-stream*.py`,
  `crt-vm-hardware-check.sh`). IP is baked into the launch line.

**Recommendation:** one sourced config — `bin/crt-config.sh` (`: "${VAR:=default}"`
exports) sourced by every `.sh`, plus a tiny `crt_config.py` that reads the
same file or shared env — carrying `CRT_REMOTE_BRIDGE_PORT`,
`CRT_AUDIO_DEV`, `CRT_EARCON_TV_DEVICE`, `CRT_EARCON_HANDSET_DEVICE`,
`CRT_WHISPER_SERVER`. Keep per-var env overrides (Zach's rule: never drop
the hardcoded override, add name-resolution alongside). Fix the broken
`plughw:0,0` defaults to the resolved capture device in the same pass.

---

## 3. Duplication

- **`potato_large.txt` vs `potato-small.txt` are byte-identical** (same
  md5 `8d6dbd71…`, 1001 bytes each). Neither is referenced by any code or
  doc (grep-clean). Both are untracked. Delete one, or delete both if they
  are stray scratch output; if the braille-art potato is real content, keep
  ONE with a consistent name. Naming also mixes hyphen and underscore —
  the repo convention is hyphen for scripts, so `potato-large.txt`.
- **book scripts** — `crt-book-game.py` (46KB) and `crt-wake-pool.py` both
  carry their own `difflib`/`SequenceMatcher` similarity + text-normalize
  logic; `crt-book-console.py`, `crt-book-answer-listen.py`,
  `crt-book-catalog.py`, `crt-book-idle-bait.py` share catalog/DB access and
  wrap/render helpers by copy. A `crt_book_common.py` (normalize, similarity,
  catalog access, render) would remove the parallel copies and let the
  wake-word fuzzy-match share one implementation.

---

## 4. Docs consolidation (~37 .md files, heavy overlap)

Many are historical or superseded. Current picture is fragmented across
`SESSION-STATE.md` (self-describes as superseding everything below its top
section), `HANDOFF.md` (2026-07-20, explicitly superseded), and
`ARCHITECTURE-REVIEW`.

**Current / load-bearing (keep at root):** `CLAUDE.md`, `.claude/SESSION-
STATE.md`, `.claude/FOCUS.md`, `ARCHITECTURE-REVIEW-2026-07-23.md`,
`STT-MECHANISM.md`, `README.md`, `SELF-REPAIR.md`, `BOOK-GAME.md` +
`BOOK-GAME-STYLE.md` (style has a mechanically-enforced color rule).

**Historical / superseded (move to `docs/archive/`):** `HANDOFF.md`
(self-superseded), `COMPUTE-STICK-MIGRATION.md` (migration abandoned per
MEMORY), `AUDIO-DEBUG.md` / `AUDIO-ROUTING.md` (dexter-era routing),
`VM-JOBS.md`, `DEVELOPMENT-WORKFLOW.md` (three-tier VM model),
`.claude/VM-BRIEFING-2026-07-21.md`.

**Design docs, mostly unbuilt — consolidate into one `DESIGN-BACKLOG.md`
with a status line each:** `IDLE-BAIT.md`, `SIDETONE.md`, `SIDEBAND.md`,
`EXPRESSIVE-TONE.md`, `PERSONA-CHANNEL.md`, `SECRETARY.md`, `SUPERVISOR.md`,
`HOOKSWITCH.md`, `DISPLAY-CALIBRATION.md`, `SCANNER.md`, `VIDEO-CAST.md`,
`STT-GATE.md`, `STT-CONFIDENCE.md`, `MORNING-REPORT-PRESENTATION.md`,
`TRIVIA-VARIETY-INVESTIGATION.md`, `RFP-GALLERY.md`, `RFP-PAYPHONE.md`,
`PHILOSOPHY.md`, `PARKING-LOT.md`.

**Recommendation:** add `DOCS-INDEX.md` (one line per doc: current /
archived / design-only) and an `docs/archive/` dir. Note `crt-mandark.sh`
already references a `POTATO.md` that does not exist — a canonical
current-topology doc is missing and would replace HANDOFF's role.

---

## 5. tmux window count vs. 1GB RAM

`crt-console.sh` spawns one session + ~9 windows (11 `new-session`/
`new-window` calls; grep): `0 claude`, `1 mono`, `2 bridge`, `3 stt`,
(`hook`, conditional), `4 book`, `5 bookidle`, `6 bookanswer`,
`7 windowswitch`, `8 stttrain`. SESSION-STATE also lists a live `9 game`.
ARCH-REVIEW measured available RAM at 120-400MB with active swap, ~8
background scripts contributing. Each window is a persistent Python process.

**Load-bearing (must stay resident):**
- `3 stt` — the sole mic reader (`crt-stt-solo.py`). Core.
- `2 bridge` + `1 mono` — the window-1 mirror the whole UX depends on.
- `0 claude` — but per SESSION-STATE the brain now runs on mandark
  (`CRT_CLAUDE_REMOTE_PORT=8993`); potato's window 0 is a secondary session.
  This is the single biggest RAM lever (~343MB / 37%) and the offload is
  already built — finish making it the default, not window 0 local.

**Could be lazy / on-demand (started by the window-switcher or secretary
only when the book game is actually invoked):**
- `4 book`, `5 bookidle`, `6 bookanswer`, `7 windowswitch`, `9 game` — the
  entire Book Game funnel. ARCH-REVIEW: trimming these freed real (if
  modest, ~27MB) pressure. They idle-poll continuously today.
- `8 stttrain` (`crt-stt-training-merge.py --loop`) — a merge loop; could be
  a periodic systemd timer instead of an always-on window.

**Recommendation [live]:** default to Claude-on-mandark (drop local window
0); make the book funnel lazy-spawned; convert `stttrain` to a timer.
Realistic resident set: stt + bridge + mono + one thin control window.

---

## 6. Test coverage gaps

`tests/` is real (run via `tests/run_tests.sh`; shell scripts get a syntax
check via `test_shell_syntax.sh`). Behavioral-test gaps, highest concern
first:

- **`crt-stt-solo.py` — NO direct test.** This is the single most critical
  process (sole mic reader, VAD, whisper dispatch, gate, predict, sideband).
  `test_stt_gate.py` / `test_stt_secretary_sink.py` cover *pieces* pulled
  out, but the VAD/segmentation/emit core is untested. Highest-value gap.
- `crt-remote-claude-bridge.py` — has `test_remote_claude_bridge.py`, good
  (it's live infra). `crt-secretary.py`, `crt-wake-arm.py`, `crt-wake-pool`
  / `-judge` / `-tally`, book scripts, `crt-claude-bridge.py` all have tests.
- **No test:** `crt-stt-stream.py`, `crt-calibration-game.py`,
  `crt-print-render.py`, `crt-tts-calibrate.py`, `crt-meter.py`,
  `crt-midi-knobs.py`, `crt-screensaver.py`, `crt-earcon-loopback-test.py`,
  `mandark-whisper-server.py` (live infra, untested), plus the dexter
  servers (moot if deleted per §1).
- Shell scripts get syntax-only coverage except the few with dedicated
  tests (monologue, hookswitch, sideband, idle-teaser, stt-feed flags,
  attach-ssh-bridge). `crt-console.sh` (the boot path) and `crt-earcon.sh`
  (routing, the recently-broken one) have no behavioral test.

---

## 7. Prioritized refactor plan (value / risk ranked)

Highest value / lowest risk first.

1. **Delete the byte-identical potato txt dupe** [offline] — trivial, zero
   risk (unreferenced). §3.
2. **Delete dead dexter/crt-vm files** [offline] — `dexter-*.py`, the four
   `crt-vm-*` scripts, `systemd/crt-vm-*`, `crt-sync-vm*.sh`. Grep-confirmed
   no live importer. §1.
3. **Fix stale-default silent-failure bugs** [offline to change, live to
   verify] — `crt-tts.py` dexter default, `plughw:0,0` defaults in the STT/
   watchdog/doctor scripts. These are latent versions of the earcon bug.
   §1/§2.
4. **Add a `crt-stt-solo.py` behavioral test** [offline] — VAD boundary /
   emit / gate logic with synthetic audio frames. Guards the most critical,
   currently-untested process. §6.
5. **Introduce a single config source** [offline to write, live to verify]
   — `crt-config.sh` + `crt_config.py`; migrate port 8993, whisper URL, all
   plughw devices; resolve the scanner/bridge 8993 collision. §2.
6. **Docs consolidation** [offline] — `DOCS-INDEX.md`, `docs/archive/`, fold
   design-only docs into `DESIGN-BACKLOG.md`, write the missing current-
   topology `POTATO.md`. Pure content move, no code risk. §4.
7. **Extract `crt_book_common.py`** [offline, test-guarded] — dedupe
   similarity/normalize/catalog/render across book + wake-pool. §3.
8. **Make the book funnel lazy + Claude-on-mandark the default** [live] —
   the real RAM win; needs hardware to confirm the switcher still spawns
   book on demand and escalation still routes. §5, ties to ARCH-REVIEW's
   central question.
9. **Convert `stttrain` loop to a systemd timer** [live] — removes one
   always-on process. §5.

Items 1-7 are nightly-batch-safe (offline, git-revert-gated per
`SELF-REPAIR.md`). Items 8-9 need potato up and a human ear/eye.
