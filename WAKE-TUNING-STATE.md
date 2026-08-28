# Wake-word self-tuning state

Living journal for the autonomous wake-word judge (`bin/crt-wake-judge.py`,
2026-07-21, Zach's direct ask: "call claude, if it got ignored, tweak. if
it sees a lot of attempts to wake it failing... tweak. but also be
available to help"). Every wake event (exact wake word, exact wake-pool
match, or fuzzy cluster match) fires a background, rate-limited `claude -p`
call with the triggering text + match details. That judge call decides
whether the wake was good or bad, and may edit:

- `~/.crt/wake-pool-dict.txt` -- remove a specific bad word
- `~/.crt/wake-tuning-config.json` -- the live per-source fuzzy cluster
  minimums / close-ratio (overrides `crt-wake-pool.py`'s
  `DEFAULT_CLUSTER_MIN_BY_SOURCE`/`FUZZY_CLOSE_RATIO` code defaults)
- this file's Judgment log -- ONLY when a call actually moves one of the
  two knobs above, to record WHY (crt#79: this file no longer gets an
  entry per wake event, just per tuning change, so the log measures
  tuning rather than traffic)

Every event, tuning change or not, is also recorded to
`~/.crt/wake-judge-events.log` (one JSON object per line, capped at 500)
by the script itself rather than by the judge call -- that's the full
history a judge reads to spot a *pattern* of failures; this file's
Judgment log is only the record of when tuning actually moved.

**Ground truth signal for "was this wake genuinely wanted":** did a real
follow-up utterance arrive and get dispatched within the arm window
(`consume_arm_with_followup` fired), or did the window time out with the
follow-up never coming (`check_arm_timeout` fired with nothing to send,
or with only a leftover fragment nobody ever continued)? A consumed
follow-up is strong evidence the wake was wanted; a timeout is evidence
it wasn't -- but a SINGLE timeout should never trigger a tweak on its own
(could just be Zach getting distracted after a genuine wake, or leaving
mid-thought) -- look for a *pattern* before acting, per Zach's own
framing ("a lot of attempts... failing").

**Starting values (2026-07-21, before any live tuning data):**
- `FUZZY_CLOSE_RATIO`: 0.72
- `cluster_min_by_source`: `{"dict": 2, "book-title": 4}`
- Reasoning: a live session's actual pool was found to be ~90% noisy
  book-title words (confederacy, dunces, lolita, cinema, etc. -- nobody
  says these to address a console), which false-armed on ordinary
  conversation ("Confederacy!" armed and silently ate 8s with no
  follow-up). Book-title words need much stronger corroboration
  (originally 2, raised to 4) than deliberately hand-seeded dict words.

## Judgment log

Entries land here only when a judge call actually changes a tuning knob
(crt#79). Older per-event entries, from before that fix, were reaped to
`vault:crt/wake-judge-log-20260825.md` -- this file is inside a shrink-only
prose ratchet.
