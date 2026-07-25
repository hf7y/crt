# crt as a phone secretary, not a raw Claude Code terminal

**Reframing (2026-07-19):** the ultimate goal isn't "STT typed into Claude
Code." It's a **secretary-like service** reached via the handset — Claude Code
is the backend brain, but the phone interaction should feel like talking to an
assistant, not dictating into a terminal. This file tracks that direction so
it isn't lost; not fully implemented yet, most of it is design + a couple of
supporting scripts (TTS, pager) that will be reused by whatever wrapper
eventually replaces the raw "type into Claude's pane" model.

## Output channels, by length/urgency
- **Printer (Phomemo M02, `bin/catprint`)** — the channel for anything long:
  job/report status, logs, anything you'd scroll through. Long text does NOT
  belong on the CRT.
- **CRT** — short status + interactivity only. If something longer genuinely
  needs to show there, it scrolls **slowly** rather than dumping — see
  `bin/crt-pager.py` (line-by-line auto-scroll, pause/resume/jump via the
  shared control file, jog-able once a MIDI knob is wired to it).
- **TTS through the phone earpiece** (`bin/crt-tts.py`, calibrated via
  `bin/crt-tts-calibrate.py`) — short spoken confirmations for the person on
  the handset. This is the "secretary" voice.
- **TTS through the TV** (`bin/crt-announce.sh`, rate-limited to 1/15min) —
  for getting **Chris's** attention when he's in the room but not on the
  phone. He can only respond by talking into the handset (no clicking/typing).
  See `AUDIO-ROUTING.md` for why this is likely a host (Windows), not guest
  (VM), problem, and the current state of that bridge (not yet built).

## What a "secretary" interaction should feel like (not yet built)
Rather than every utterance being typed verbatim into Claude's terminal input
(today's model, still the working baseline), a secretary wrapper would:
1. Listen for a request ("what's my nightly build status", "tell Chris the
   report's ready", "read me the last thing that failed").
2. Hand it to Claude Code as a scoped, structured ask — not a raw keystroke
   feed — and get back a response.
3. **Speak** a short answer through the earpiece (crt-tts.py), and/or print a
   full report to the Phomemo, and/or scroll a longer answer on the CRT
   (crt-pager.py) if it must be read there.
4. Never assume the caller can read a screen — voice in, voice/print out,
   CRT only for short status glances.

## Current implementation status
- TTS engine + calibration: written, not yet audited by ear (`bin/crt-tts.py`,
  `bin/crt-tts-calibrate.py`). Deployed + smoke-tested (exit 0, no errors) on
  crt-vm 2026-07-19 via `espeak-ng`.
- Speak-back debug loop (`bin/crt-stt-speakback.sh`): runs the STT engine in
  **debug mode (stdout only, NOT wired to Claude)** and speaks back
  "heard: ..." for each transcription — lets a person on the handset debug
  the mic/STT purely by ear. Running live on crt-vm's `stt` tmux window as of
  2026-07-19 14:40 (replaced the old stt-feed.sh+crt-levels.sh pipeline for
  this debug session — restore with `crt-console.sh` for the normal
  Claude-wired flow).
- Pager (`bin/crt-pager.py`): written, syntax-tested with synthetic text
  (wraps to 40 cols, scrolls, footer shows page%/END). Not yet wired to any
  real Claude output or a MIDI knob.
- The secretary wrapper (steps 1-4 above) has a first real implementation:
  `bin/crt-secretary.py` (2026-07-19). Takes one utterance, decides (a)
  whether it's answerable **locally** with zero Claude call — "what's up"/
  "any reports"/"anything new" etc. read straight from
  `~/reports/crt/LATEST.md` + `.claude/QUESTIONS.md` and get a spoken
  summary + offer to print full detail (`bin/crt-print.sh` -> PIL render ->
  `catprint`, also new this session) — or (b) needs Claude: sends via
  `tmux send-keys` as today, polls `tmux capture-pane` for the reply to go
  idle, then speaks it if short or speaks-a-summary-and-prints if long.
  **NOT hardware-verified** — the local-answer path was tested standalone
  against real report/question files and works; the Claude-routing path's
  idle-detection (poll capture-pane until unchanged for N seconds) is an
  untested heuristic, the riskiest part of this design, see the script's
  own header. **Not wired into `stt-feed.sh` yet** — that still does raw
  `tmux send-keys` for every utterance; swapping it to call
  `crt-secretary.py` per utterance is the next step, deliberately not done
  automatically this session since it changes the live default pipeline
  and nobody could watch it run.

## The three outcomes of a Claude escalation, and why they are three (2026-07-25)

Once Claude Code moved off potato onto mandark behind a reverse tunnel, an
escalation stopped having two possible endings and started having three.
They were collapsed into one spoken line for a while, in both directions,
and each collapse was a separate bug:

| outcome | what actually happened | the line |
|---|---|---|
| **answered** | it landed, a reply was read | the reply itself |
| **never sent** | the tunnel/bridge was down, or tmux refused the keys | `BRAIN_UNREACHABLE_LINE` — "I can't reach my brain right now, so that didn't go anywhere" |
| **sent, reply unobserved** | it landed; `capture_pane()` couldn't be read afterwards | `REPLY_UNOBSERVED_LINE` — "I sent that to Claude, but I lost my view of the answer partway through" |

The rule this encodes: **the console may only report what it observed.**
"I sent that to Claude but didn't catch a reply — check the screen" is
reserved for the one case where all three of its claims are true — it was
sent, a reply was genuinely watched for, and the screen has whatever came.
Using it for the other two was wrong twice each: nothing was sent, or
nothing was watched.

Mechanically, this rests on `capture_pane()` returning `None` (unreadable)
rather than `""` (read, empty). Anything that collapses those two again
re-opens both bugs — the second one loudly: with no baseline to diff
against, every line on the pane counts as new, so 200 lines of scrollback
get spoken into the earpiece and printed on the Phomemo. Covered by
`tests/test_secretary.py`'s `TestUnobservedReply`, which injects at the
bridge socket rather than stubbing `capture_pane()`, because stubbing it
reproduces neither failure.
