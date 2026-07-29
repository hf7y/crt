# STT error patterns for this room / mic / whisper setup

Prose notes. The mechanical substitution dictionary is
`crt-repo/bin/stt-fixups.json` (see `crt_fixups_store.py`); this file is
for patterns that are not a word->word mapping and so cannot live there.

Started 2026-07-29 by the dexter-side console. Grounded in
`~/.crt/gate.log` and `~/.crt/stt.log`, not in impressions.

---

## 2026-07-29, 03:24-04:22 — first long session with the `potato` wake
## word actually in force

Context worth recording: the wake word had been *documented* as `potato`
since 2026-07-28 but was never in force on a cold boot (it was exported
below the `exec` line in `~/.bash_profile`). This window is the first
real data on it. 29 utterances: 6 addressed, 23 dropped.

### The gate is working, and better than the human thinks

All 6 addressed utterances passed. Zero false negatives observed. But
Zach says the wake word **two or three times per request**:

    "Potato. Let's get that margins. Potato. Potato I lost you."
    "Yo yo yo potato yo potato It's Zach..."
    "potato, potato, we're trying to get the margins here."

That is a person compensating for a gate they do not trust — a habit
formed during the three days the console was actually dark, or during the
period the wake word was silently `claude`. **Do not read the repetition
as the gate needing help.** If anything it is evidence the console owes
him a visible/audible "I heard you" so he can stop doing it. The
`addressed` earcon is supposed to be exactly that, and it was playing to
the handset earpiece (nobody holding it) for this whole period — fixed
2026-07-29, effect not yet observed.

### Trailing "..." is a hallucination tell

Whisper emits a trailing ellipsis on low-confidence or truncated
segments. Tonight's examples, all from ambient room noise with no
corresponding speech:

    "Hey, Potato! Ready to hear..."
    "I guess they get in the ghost. Like, you see the good. Just not making it like I..."
    "I'm not sure. Dude, you gotta set yourself. Where? Oh. This is the... Oh my God. This is..."

The first one **cleared the wake gate and escalated a real request to the
brain** at 03:40:01. It is short, it contains "Potato", it is
grammatically plausible, and nothing was said. Confirmed not an echo of
the console's own speech: no TTS process ran and `~/.crt/announce.lastrun`
was six days stale.

**Candidate heuristic, not yet implemented:** short utterance (< ~8
words) + contains the wake word + ends in `...` => treat as suspected
hallucination, do not escalate. Worth testing against the log before
wiring in; the risk is dropping a genuine short command like "Potato,
stop..." — but a genuine short command is very unlikely to carry the
ellipsis, because that punctuation is whisper's uncertainty, not the
speaker's.

### The room is two people talking, not one person dictating

Nearly every drop is multi-sentence cross-talk between Zach and someone
else. The gate handles this correctly. But it means **VAD segments are
long and topic-mixed**, so a request spoken mid-conversation arrives
glued to unrelated speech:

    "Love to see you. No, I can't read the whole line. Potato, let's do
     the margin config. It's fucking self-aware that I need to adjust the
     margins."

Three separate speech acts in one utterance: an aside to the other
person, an answer to the console's previous question, and a new command.
Anything downstream that treats an utterance as one intent will get this
wrong. **Read past the wake word for the actual imperative; do not assume
the whole utterance is addressed to you even when the gate passed it.**

### Proper nouns and domain jargon are unreliable in chatter

From tonight, all almost certainly wrong and unrecoverable without
context: "seat-beak", "Mayjax", "Rescimate", "cornering dead man
squitches", "Ronald Washington", "stream-washing". These appear in
dropped ambient speech, so they cost nothing today — but they are a
warning about what happens to an unusual filename or hostname spoken
aloud. **When a request names a file/host/command, confirm it rather than
acting on the transcription.**

### Confirmed good

- "potato" itself transcribes reliably, including mid-sentence and
  lowercase. It is a strong wake word for this mic — unlike "claude",
  which has a documented history of landing as "slide" and "clot".
- Profanity transcribes accurately, which is a decent proxy for the
  acoustic model being healthy on this input.
- Numbers and short imperatives survive well ("40 characters or less",
  "window one").

---

## 2026-07-29, 04:31-04:35 — two more, both observed live

### `pateto` — first confirmed FALSE NEGATIVE on the wake word

    04:31:58  dropped (no wake word): "Yo, yo, Pateto, thanks. Pateto,
              can we get the window one? Where is it?"

Addressed to the console, twice in one utterance, and dropped. Whisper
substituted the medial /oʊ/ with /ə/ and dropped the second /t/ release:
potato -> pateto. Zach did not notice it had been dropped; he simply
re-asked 20s later.

**Not yet added to stt-fixups.json** — that file is tracked in the repo
and potato's checkout is mid-work on another branch, so adding it needs a
lane picked first. It belongs there: `addressed_to_console()`
(crt-stt-solo.py:971) treats any fixup whose learned intent IS the wake
word as load-bearing for the gate, and FixupsFile hot-reloads, so the
entry takes effect with no restart.

    "pateto": {intent: "potato", type: "wake-word-alias",
               confidence: "auto", note: "observed 2026-07-29 04:31,
               dropped a real request; needs a second sighting"}

Expect neighbours in the same family: `potatoe`, `patato`, `potaydo`,
`per tato`. Watch for them before hard-coding a whole set — one confirmed
sighting is not a pattern.

### Repetition-loop hallucination on laughter

    04:34:44  "...Heh. Heh. Heh. Heh. Heh. Heh. Heh. Heh. Heh. Heh.
               Heh. Heh. Heh. Heh."

Fourteen identical tokens. Whisper's known repetition failure on
non-speech audio: it locks onto a token and cannot exit until the segment
ends. Laughter is the trigger here, and this room produces a lot of it.

Consequence to watch for: the repetition PADS the utterance. A short real
command followed by laughter can arrive as a long utterance mostly made
of junk, which may push the real content out of any length-based
heuristic or truncate it in a 40-column display. The gate handled this
one correctly (no wake word present).

**Candidate cleanup, not implemented:** collapse runs of >3 identical
short tokens before the gate sees the text. Cheap, and it makes both the
gate decision and anything logged to thoughts.log more honest about what
was actually said.
