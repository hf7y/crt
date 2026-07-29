# Voice session findings, 2026-07-29 (02:00-04:45)

Written by the dexter-side console while watching potato's voice path
live. Everything here was observed in `~/.crt/gate.log`, `stt.log`,
`thoughts.log`, `brain-unreachable.log`, or in the brain's own tmux pane —
not inferred.

Filed as its own document rather than into `.claude/FOCUS.md` because
`focus-commit` (the multi-writer-safe committer this project requires for
FOCUS.md) **is not installed on dexter**. See "Ecosystem gaps" below.

---

## What got fixed and verified

| What | Commit | Verified by |
|---|---|---|
| Console config out of `~/.bash_profile` into `~/.crt/console.conf` | `a8a2455` | stt window restarted with zero config env; all 15 `CRT_*` correct from files |
| Brain starts with permissions bypassed; parked states detected | `a620761` | caught the bypass-confirmation screen on its first live run |
| Voice worktree + calibration harness + prompt injection | `a620761` | `stage` runs 9 ok / 1 deliberate FAIL |
| `say` sources config, waits long enough | `f07cd1f` | round trip: question → brain → window 1 |
| Window 1 honors left/top margin instead of only shrinking | `ff424b3` (brain, on `voice`) | **Zach, by eye: "the margins look great"** |

`ff424b3` is the one that matters: it is the first durable repo change
this console produced from spoken input, and the human confirmed it on the
actual tube. `crt-monologue.py` had been consuming the margin in
`viewport()` as a width/height SHRINK only, then homing the cursor to
`\x1b[H` and printing at physical column 1. `left=2` bought nothing — the
box got narrower from the right while the edges overscan actually eats
stayed put.

---

## Open, in rough order of how much they cost the human tonight

### 1. The wake gate makes conversation structurally impossible

The brain asked Zach to read two letters off a calibration ruler. He
answered twice:

    04:36:03  dropped (no wake word): "...A-B-C-D-E"
    04:36:23  dropped (no wake word): "V W X and the indentation took off Y and Z."

Both dropped. **Answers to questions are short and never contain the wake
word.** "A and Z", "yes", "one more to the left" — every one of them fails
the gate. A console that asks questions cannot hear the answers.

The sticky wake-arm window exists for exactly this
(`bin/crt-wake-arm.py`, `CRT_WAKE_ARM_SECS` default 12) and is ENABLED on
potato. It is not holding: `~/.crt/wake-arm.state` read `0.000` seven
seconds before the first dropped answer. Either it is not being armed on
an addressed utterance, or it is being published closed immediately.
`publish_arm_window()` is called "after EVERY arm-state transition and
nowhere else" — start there.

This is the single highest-value fix on this list.

### 2. Nothing serializes utterances

Up to **5 concurrent `crt-secretary.py` processes** were alive at once,
one per utterance, each independently polling the brain's pane and each
writing `...composing` to window 1. Replies land out of order against a
background of other waiters' placeholder text. It drains (oldest seen: 88s)
so it is not a leak, but with 1-3 minute brain turns it destroys the
thread of a conversation. Zach said "did I lose you" three times while the
brain was working normally.

No lock, no "still working on the last one", no cancel-and-replace.

### 3. Long turns look identical to death

The brain used to answer in ~2s. With bypass and real tool work it now
takes **28s to 3m12s**, and window 1 shows one static `...composing` for
the entire time. The `thinking` earcon fires once at escalation and then
silence.

Cheap fixes: repeat the `thinking` earcon every ~20s while a reply is
outstanding; animate `...composing` with an elapsed counter.

### 4. The `»` marker filter is enforced NOWHERE

The brain marks its user-facing lines with a leading guillemet, correctly.
Nothing on potato filters for it: `crt-claude-bridge.py` (pid 866, up 27h)
still watches **window 0's local pane**, and the brain moved hosts. So
window 1 renders the brain's full working output. Observed on the tube:
hook messages, `PostToolUse` notices, the question echoed back, and — once
the brain started editing code — **a unified diff, line numbers and all**
(`77 +`, `78 +`, `79 +`).

Zach, reading his own tube: *"I don't know what this number 79 is, but..."*

Also renders the `»` characters as literal text, so multi-line answers run
together with stray guillemets. The brain has started noticing its own
output is not landing.

The fix is a design decision — where does the filter live now that the
brain is on another host — which is why it is left failing loudly in
`crt-voice-calibration.sh check` rather than guessed at.

### 5. The calibration asks for something never rendered

The brain asked for the leftmost and rightmost readable letters on a
ruler. **No ruler was ever put on the tube.**
`bin/crt-calibrate-display.py show` is the thing that renders it; its
header says it has never run against real hardware. The brain cannot see
the screen and the human cannot see what the brain is imagining. Neither
side knew the other was missing.

### 6. potato has no voice at all

No `piper`, no `~/.crt/voices/`, no `espeak`/`espeak-ng`. `crt-tts.py`
exists with no engine behind it, which is why every reply logs
`SPOKE NOTHING (or piper...)`. **The console has never spoken a word.**
Earcons are its entire audible vocabulary — which is why the
earcons-to-the-wrong-device bug mattered more than it looked.

Observed live: Zach, to the room — *"Also, I can't hear you."*

### 7. `crt-secretary.py` exits 0 on failure

It prints "I sent that to Claude but didn't catch a reply" and returns 0.
An exit-0 no-op, the exact thing this project's build discipline names.

---

## STT findings

Full prose notes are on potato at `~/.crt/stt-corrections.md` (146 lines,
started tonight — the file did not exist before). Highlights:

- **`pateto`** — first confirmed FALSE NEGATIVE on the wake word.
  04:31:58 dropped a real request, twice in one utterance. Belongs in
  `stt-fixups.json` as a wake-word alias (`addressed_to_console()` treats
  any fixup whose intent IS the wake word as load-bearing, and the file
  hot-reloads). Not added yet — tracked file, and potato's checkout is
  mid-work on another branch.
- **Trailing `...` is a hallucination tell.** One such phantom
  (`"Hey, Potato! Ready to hear..."`) cleared the gate and escalated a
  real request at 03:40:01 with nobody speaking. Confirmed not a TTS echo:
  no TTS exists.
- **Repetition-loop on laughter** — `"Heh."` fourteen times. Pads
  utterances with junk.
- **Zach says the wake word 2-3x per request.** He is compensating for a
  gate that works. What he needs is the `addressed` earcon he could not
  hear, because it was playing into an earpiece nobody was holding.
- **Utterances contain 2-3 separate speech acts** glued together by long
  VAD segments (two people in the room). Do not treat a passed utterance
  as one intent.

---

## Deployment topology, corrected

- **potato's `origin` is `/home/zach/git-remotes/crt.git`** — a
  mandark-local path. potato has never been able to `git pull`. Deploy by
  pushing from dexter: `git push potato main` (needed
  `receive.denyCurrentBranch=updateInstead`, now set).
- **potato's checkout is currently on branch `voice`**, switched by the
  brain when it deployed its margin fix. It therefore lacks `a620761`,
  `f07cd1f` and `7e2a54d`.
- **`voice` branched from `a8a2455`**, one commit before the calibration
  harness existed — so the brain's own worktree does not contain
  `crt-voice-calibration.sh` or `voice-priming-prompt.md`. It was primed by
  tmux injection, not by reading the file. It cannot find the harness when
  asked for it.
- `voice` merges into `main` **conflict-free**; full suite ALL GREEN on
  both.
- **This repo has no GitHub remote.** `origin` is mandark. `hf7y/crt`
  exists on GitHub (private, issues enabled, zero issues) and sits at
  `68b3a4f` — missing every commit from this session.
- Still on mandark, the box the dexter move exists to escape: the whisper
  server (`CRT_WHISPER_SERVER=http://192.168.0.27:8991`), the bibquotes
  SMB share, and the git origin. dexter has no whisper install at all.

---

## Ecosystem gaps

`notify-senechal`, `check-project-busy`, `focus-commit` and
`silence-audit` are **not installed on dexter**. `~/.local/bin` holds only
`claude`, `crt-brain-shell`, node/npm/npx and two usage scripts.

Consequences, both real tonight:
- Machine-config changes made this session (potato's `~/.crt/console.conf`,
  its trimmed `~/.bash_profile`, its repo's `receive.denyCurrentBranch`)
  are **owed a senechal note that could not be filed**.
- `.claude/FOCUS.md` could not be updated safely, which is why this
  document exists.
