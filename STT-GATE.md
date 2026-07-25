# STT gate — don't call Claude on room noise/ambient conversation

**Status (2026-07-21, nightly batch): near-term gate BUILT, offline-tested,
NOT hardware-verified.** This is the near-term half of the item Zach flagged
2026-07-20 (see `.claude/FOCUS.md`'s "Now (core STT)" section for the
original ask and full context) — every utterance that clears
`crt-stt-solo.py`'s VAD was becoming a live Claude Code turn, including room
chatter never meant for the console. This file documents what actually
landed; `.claude/FOCUS.md` is the source of truth for what's still open
(a batch run couldn't edit it directly this pass — see the nightly report).

## What's built

`CRT_STT_GATE` (default `0`, opt-in) in both `bin/crt-stt-solo.py` and
`bin/stt-feed.sh`:

- **On** (`CRT_STT_GATE=1`): before a recognized utterance is typed into the
  Claude tmux pane, `addressed_to_console(text)` must return true, or the
  utterance is logged to `~/.crt/thoughts.log` (tagged `[stt-gate] dropped
  (no wake word): ...`) and dropped instead of escalated. It's still always
  logged to `~/.crt/stt.log` either way (unchanged, pre-existing behavior).
- **Off** (default): completely unchanged, always-escalate behavior — this
  flag flips nothing until a human turns it on.
- **Wake word**: `CRT_WAKE_WORD` (default `"claude"`) must appear as a whole
  word in the utterance (tokenized on word characters, so "hey claude, run
  the tests" still matches despite the comma).
- **Fixups are load-bearing now**: `bin/stt-fixups.json`'s `"slide": {"intent":
  "claude", ...}` entry (a confirmed mis-hear of the wake word) is read at
  gate time (`CRT_STT_FIXUPS` overrides the path) — any fixup entry whose
  `intent` equals the wake word counts as the wake word too. Matching is
  whole-word/whole-phrase, not substring, so "landslide" does NOT
  false-positive on the "slide" fragment.
- **Exempt**: single-word `CONTROL` keystrokes (yes/no/enter/up/down/clear/
  etc., matched in both engines' existing `CONTROL` dict) are NOT gated —
  those answer a prompt already on screen mid-interaction (a confirmation,
  a menu). Requiring the wake word there would make hands-free confirm/deny
  during an active Claude turn require repeating "claude" every time, which
  defeats the point of voice control.
- `stt-feed.sh` does not reimplement the match in bash — it shells out to
  `crt-stt-solo.py`'s `addressed_to_console()` via `python3 -c` (see the
  `addressed_to_console()` bash function near the top of the file), so the
  two engines share one implementation instead of two that can drift.

## Testing

- `tests/test_stt_gate.py` — 10 cases, pure offline unit tests against the
  real `bin/stt-fixups.json` (wake word present/absent, fixup mishear
  match, whole-word-not-substring, default-off, malformed/missing fixups
  file, custom wake word).
- `tests/test_stt_feed_gate_flag.sh` — 8 cases: default-off guard,
  `addressed_to_console()` extracted and run for real from `stt-feed.sh`
  against three utterances, plus a grep-based check that the default-off
  guard line and the gate call site are both still present (same pattern
  `test_stt_feed_secretary_flag.sh` already used for `CRT_SECRETARY`).
- Both registered in `tests/run_tests.sh`; full suite is green (see the
  nightly report for the run this landed in).

## NOT done — do not claim otherwise

- **Not verified against real room noise or a real voice** — this whole
  gate exists to solve a live-audio problem and has never run against
  actual mic input. The wake-word requirement is a real UX/false-negative
  risk (say a real command without "claude" in it and it's silently
  dropped) that only a human on the handset can actually evaluate. That's
  why it ships default-off.
- ~~**Not turned on anywhere**~~ — **STALE, and it was stale for four
  days.** `bin/crt-console.sh:193` has launched the `stt` window with
  `CRT_STT_GATE=1` since 2026-07-21 (that file's own comment block above
  the line records why: `SINK=secretary` alone still escalated nearly
  every utterance to Claude, because casual room speech matches no
  playbook). So this gate is the live boot default on potato, not an
  opt-in a human has yet to take. Corrected 2026-07-25, fourteenth
  nightly cycle, while establishing that a wake-word utterance really
  does go to Claude — the premise `bin/crt_wake_gate.py` rests on. It is
  still true that `bin/crt-console-solo.sh` does not set it, and that
  `crt-stt-solo.py`'s own default is `0`.
- **The long-term replacement (a real local text-handling/intent service
  that escalates to Claude only when it doesn't know what to do, per the
  original FOCUS.md item's point 2) is NOT started.** This is only the
  near-term gate; don't conflate the two.
