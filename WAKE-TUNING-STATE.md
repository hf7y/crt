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
- this file -- to record WHY, so the next judge call (and any human
  reading this) has continuity of reasoning rather than starting cold
  each time

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

- 2026-07-21: Trigger "Potato!" (match kind: pool). Outcome: consumed --
  follow-up "! Alright, we're back. So yeah, just now I lost you. I should
  not have lost you. I should not be on the default screen right now.
  You're fully clear to make changes to this. It's a virtual machine. make
  sure this feels closer to interacting back and forth. Thanks. Well, I'm
  finally able to debug on things." was dispatched. Verdict: GOOD wake,
  clean case. Explicit console-directed content: reporting a lost-connection
  bug ("just now I lost you", "should not be on the default screen"),
  granting explicit permission to modify the VM ("you're fully clear to
  make changes ... it's a virtual machine"), and a UX goal ("make sure this
  feels closer to interacting back and forth"). Yet another consumed event
  on pool word "potato" -- pattern remains fully positive across every
  judged event on this word (well past a dozen now). No tuning change.
  Note: the described bug (losing connection, landing on "default screen")
  echoes prior entries about losing mid-utterance speech/debug window
  flipping -- worth surfacing to Zach as a recurring live issue, separate
  from this judge's tuning-file scope.

- 2026-07-21: Trigger "Potato" (match kind: pool). Outcome: consumed --
  follow-up "Okay, I'm losing you in the middle of speaking and then it's
  flipping through the debug window and then looking for the watch for it
  yet. So I need to stay on window one for longer." was dispatched. Verdict:
  GOOD wake, clean case. Explicitly console-directed feedback -- describing a
  real bug (losing speech mid-utterance, debug window flipping unexpectedly)
  and a concrete request (stay on window one longer). Yet another consumed
  event on pool word "potato" -- pattern remains fully positive across every
  judged event on this word (well past a dozen now). No tuning change. Note:
  the described bug itself (losing mid-utterance speech, window flipping
  during debug) is a live functional issue worth surfacing to Zach directly,
  separate from this judge's tuning-file scope.

- 2026-07-21: Trigger "Potato. Potato. Potato. Potato." (match kind: pool).
  Outcome: consumed -- follow-up ". Potato. Potato. Potato. Potato. potato
  potato. Oh, it's it's it's coming up pretty well. Those are all potato. So
  it's really all educated today. Well, you don't know the other things I'm
  going to work on. This is what you see. All right. Potato potato potato
  potato potato It's all potato. Potatoes are looking like a good watch
  word." was dispatched. Verdict: GOOD wake, clean case. Explicitly meta --
  Zach is directly evaluating the wake word itself ("coming up pretty well",
  "Potatoes are looking like a good watch word"), same self-testing pattern
  as the "use the alias potato for now...to get a sense of what potato
  results in TT" entry above. This is now a very large stack of consumed
  events on pool word "potato" with zero bad-leaning data across all of
  them -- "potato" is confirmed as Zach's deliberate, low-risk test wake
  word. No tuning change.

- 2026-07-21: Trigger "Windows 0 Claude for clarity because Claude does not
  pick up." (match kind: exact). Outcome: consumed -- follow-up "Windows 0
  for clarity because Claude does not pick up. In the STT, I'm going to use
  the alias potato for now. can be conducted and exercise. to get a sense of
  what potato Results in TT. when I say it seven and then update the Watch
  words. to also call you on those. I have more phones." was dispatched.
  Verdict: GOOD wake, clean case. Content is explicitly meta -- Zach
  describing his own STT-testing methodology ("use the alias potato for now
  ... to get a sense of what potato results in [S]TT ... update the Watch
  words") -- this is Zach directly narrating the same wake-word tuning
  process this judge log tracks. Reinforces that exact-match wakes keep
  showing no bad pattern. No tuning change. Note: confirms "potato" is a
  deliberate, ongoing test alias Zach chose on purpose (not an accidental
  STT artifact) -- consistent with earlier speculation in this log.

- 2026-07-21: Trigger "Hello, potato." (match kind: pool). Outcome:
  consumed -- follow-up "Hello, . Tada, hello. I would like you to identify
  yourself. Oh, potato. I would like you to identify yourself with Hannah."
  was dispatched. Verdict: GOOD wake, clean case. Direct address and an
  explicit request ("I would like you to identify yourself") -- clearly
  console-directed despite garbling ("with Hannah" is plausibly a mis-hear,
  maybe "with a name" or similar). Yet another consumed event on pool word
  "potato" -- pattern remains fully positive across every judged event on
  this word (well past a dozen now). No tuning change.

- 2026-07-21: Trigger "Hello, hello, potato can we can we go to wind? Oh,
  yeah, we're in window one right now. Thank you very much. I just want to
  get some Word that you are the quad running on window zero" (match kind:
  pool). Outcome: consumed -- follow-up dispatched, extending with "Hello,
  I'm trying to reach the clock on Windows 0. Trying to reach the claw, when
  does he run?" Verdict: GOOD wake, clean case. Explicit console-directed
  content throughout: window-switching talk ("window one", "window zero"),
  direct address ("you are the quad running on window zero" -- "quad" is
  likely a mis-hear of "console"), and "trying to reach the clock/claw on
  Windows 0" reads as Zach trying to reach the console process on a specific
  tmux window. Yet another consumed event on pool word "potato" -- pattern
  remains fully positive across every judged event on this word (now well
  past a dozen). No tuning change.

- 2026-07-21: Trigger "Potato" (match kind: pool). Outcome: consumed --
  follow-up "data. I'm trying to reach the cloud in Windows 0. Can I get a
  confirmation of the other cloud on the machine, not through the SSH?
  Patera, can you move me to... window Taro, can you move me to Wonder
  Woman?" was dispatched. Verdict: GOOD wake, clean case. Explicit console
  commands (window switching, requesting a confirmation "not through SSH")
  -- clearly console-directed despite heavy garbling ("cloud" for
  "window"/"console"? "Patera"/"Taro" both plausible mis-hears of "potato"
  again, alongside earlier "Tatum" note -- worth adding to the phonetic
  mental-model file if a dedicated one gets built). Yet another consumed
  event on pool word "potato" -- pattern remains fully positive across
  every judged event on this word (now well past ten). No tuning change.

- 2026-07-21: Trigger "running on this computer. Totally different computer.
  I've never been inside the other computer." (match kind: pool, matched
  word likely "computer"). Outcome: consumed -- a long follow-up was
  dispatched, including content about "someone else who's not me on the
  other computer" and "it left a note for the other guy." Verdict: GOOD
  wake. Trigger/follow-up content reads as rambling, possibly confused
  chatter about computers/identity, not clearly console-directed -- but per
  the ground-truth rule, a real dispatched follow-up is strong evidence of
  a wanted wake regardless of topic. This is another consumed event on pool
  word "computer" specifically, adding a third GOOD data point on that word
  (alongside "Photoshop it" and "could be in the receipt") against the
  single earlier timeout-with-leftover bad-leaning entry -- pattern on
  "computer" continues to lean positive/mixed, not bad. No tuning change.

- 2026-07-21: Trigger "Potato, potato." (match kind: pool). Outcome:
  consumed -- follow-up ", potato. So yeah, okay. So the problem is that
  the Gate has been too long and the unfollow work just never stops track.
  Later There you go. Did it?" was dispatched. Verdict: GOOD wake. Content
  is garbled (likely "the gate/wait has been too long", "workflow"->
  "unfollow work", "never stops tracking") but reads as Zach describing an
  ongoing problem and checking if the console registered it ("did it?") --
  console-directed intent, consistent with the ground-truth rule regardless
  of transcription quality. Yet another consumed event on pool word
  "potato" -- pattern remains fully positive across every judged event on
  this word (now well past half a dozen). No tuning change.

- 2026-07-21: Trigger "Alright, hello. So this is Zach trying to get a whole
  little potato. Hello, potato." (match kind: pool). Outcome: consumed --
  follow-up "Alright, hello. So this is Zach trying to get a whole little .
  Hello, potato. and I'll see you in the next video. I just want to see
  output from the cloud on Windows 0 coming out on Windows 1. Potato.
  Potato. I don't know if this is that." was dispatched. Verdict: GOOD wake,
  clean case. Explicit self-identification ("this is Zach trying to get...")
  plus console-relevant content (wanting to see output on a window/screen).
  Yet another consumed event on pool word "potato" -- pattern remains fully
  positive across all judged events on this word. No tuning change.

- 2026-07-21: Trigger "Hello, Claude. Tell me about the books that I've
  scanned that you can find on the machine." (match kind: exact). Outcome:
  timeout-with-leftover -- follow-up dispatched alone as "Hello, . Tell me
  about the books that I've scanned that you can find on the machine."
  (nobody continued within the arm window). Verdict: GOOD wake, clean case.
  Explicit "Hello, Claude" address plus a genuine, on-topic question
  (referencing the ISBN-scanning book-catalog project) -- textbook
  console-directed speech, same shape as the other exact-match timeout
  entries below ("plug it into an old TV", "hello Claude...wake words more
  sensitive"). No tuning change -- exact-match wakes continue to show no
  bad pattern; this is simply a timeout because the request was
  self-contained and needed no further follow-up, not evidence of
  over-triggering.

- 2026-07-21: Trigger "Hello, Potato!" (match kind: pool). Outcome:
  consumed -- follow-up "Hello, ! - Potato, hello. Hey, potato, I'm talking
  to you. Hello. Alright, next, we're in. Uh, it's fine. This is my message.
  I wanna spend it. I want to switch to the end of Father Hundif. I want to
  switch to the other window." was dispatched. Verdict: GOOD wake, clean
  case. Directly addressed to the console ("Hey, potato, I'm talking to
  you") plus an explicit console command ("I want to switch to the other
  window" -- "Father Hundif" is likely a garbled window name/number). Fifth-
  plus consumed event on pool word "potato" -- pattern remains fully
  positive, zero bad-leaning data on this word across all judged events. No
  tuning change.

- 2026-07-21: Trigger "Potato" (match kind: pool). Outcome: consumed --
  follow-up "That's not what I said. It got it wrong. But can we switch
  over to window one? And can you just say something to me? Just talk to
  me. Mmm." was dispatched. Verdict: GOOD wake, clean case. Explicitly
  console-directed content ("switch over to window one" is a direct
  command, "say something to me, just talk to me" is direct address) plus
  Zach flagging a mis-transcription ("that's not what I said, it got it
  wrong"). Fourth-plus consumed event on pool word "potato" -- pattern
  remains fully positive, no bad-leaning data at all on this word. No
  tuning change.

- 2026-07-21: Trigger "Hello, potato!" (match kind: pool). Outcome:
  consumed -- follow-up "Hello, ! Alright, so this is me giving you the
  prompt. Just make sure they show on the screen to let me know that you
  got me. Potato! Hey potato, so I think here's the problem. It's that I'm
  still just seeing stuff on the depot screen. I don't know, maybe you
  should stop crying." was dispatched. Verdict: GOOD wake, clean case.
  Explicitly console-directed ("make sure they show on the screen to let
  me know that you got me") plus more meta content about a screen-display
  problem ("still just seeing stuff on the depot screen" -- likely a
  mis-hear of "console screen" or similar). Third consumed event on pool
  word "potato" -- pattern remains fully positive, no bad-leaning data at
  all on this word. Note: "depot" here is plausibly another mis-hear
  adjacent to console/console-screen vocabulary, worth watching alongside
  the earlier "Tatum"<-"potato" mental-model note. No tuning change.

- 2026-07-21: Trigger "This is Zach speaking into the computer. Potato."
  (match kind: pool, word: "potato"). Outcome: consumed -- follow-up
  "This is Zach speaking into the computer. . Oh, Tatum. Yeah, so this is
  Zach speaking. Hello. Hey! I'm running this exact speaking. Let's...
  let's see what's up!" was dispatched. Verdict: GOOD wake, clean case.
  Explicitly self-identifying and addressing the console ("This is Zach
  speaking into the computer", "let's see what's up") -- textbook
  console-directed speech. Second consumed event on pool word "potato"
  (first one above also consumed cleanly with console-directed content) --
  pattern now fully positive on this word, no bad-leaning data at all. Note:
  "Tatum" is likely a mis-hear of "potato" itself (phonetically close) --
  worth a mental-model entry for STT garbling of "potato" -> "Tatum" if it
  recurs. No tuning change.

- 2026-07-21: Trigger "And as there's no one will eventually result in that
  way. I'm already there. If you really go through the drum block, you
  really go through the drum block and it's scanning." (match kind: pool).
  Outcome: consumed -- a long follow-up was dispatched, including explicit
  console-relevant content ("for entering books that don't have codes",
  "testing system", "Hello This is Zach trying to get a hold of the clog
  here"). Verdict: GOOD wake. Trigger itself is garbled ("drum block"/
  "scanning" likely mangled ISBN-scanner talk -- see book-catalog project
  memory) but the follow-up both dispatched and contains genuinely
  console-directed content (a deliberate test utterance). Consistent with
  the ground-truth rule and with the broader pattern that consumed
  pool-source wakes keep showing no bad signal. No tuning change.

- 2026-07-21: Trigger "I mean, I guess the computer could be in the receipt."
  (match kind: pool, matched word likely "computer"). Outcome: consumed --
  follow-up "And after, after." was dispatched. Verdict: GOOD wake. Trigger
  content is unrelated/garbled chatter (receipt?) but a real follow-up arrived
  and dispatched -- per the ground-truth rule this is strong evidence of a
  wanted wake regardless of topic. Notably this is a second data point on
  "computer" landing on the GOOD side (alongside the earlier "Photoshop it"
  consumed entry), versus the one earlier timeout-with-leftover bad-leaning
  entry -- pattern on "computer" is now mixed, not one-sided bad, so still no
  tuning change. Continue watching "computer" specifically for repeat
  timeouts before removing it from the pool dict.

- 2026-07-21: Trigger "Lost it again. Human. Humankind." (match kind: pool,
  matched word likely "human"). Outcome: consumed -- follow-up "human" was
  dispatched. Verdict: GOOD wake. Terse, ambiguous content on both sides
  (trigger and follow-up are just "human"/"humankind" repeated), but a real
  follow-up arrived and dispatched -- per the ground-truth rule this is
  strong evidence of a wanted wake regardless of how thin the content is,
  same shape as the many other consumed pool-match entries below. First
  judged event on pool word "human"; no prior pattern to compare against.
  No tuning change.

- 2026-07-21: Trigger "Film!" (match kind: pool). Outcome: consumed --
  follow-up "Yes, so I'm trying to interact with the quad session." was
  dispatched. Verdict: GOOD wake. Follow-up is explicitly about
  interacting with a console session -- clearly console-directed. First
  judged event on pool word "film"; consumed cleanly, consistent with the
  broader pattern that consumed pool-source wakes keep showing no bad
  signal regardless of trigger topic. No tuning change.

- 2026-07-21: Trigger "Well, I think it's the last thing about the floor.
  It's like slippery, so some examples fall down." (match kind: pool).
  Outcome: consumed -- follow-up "- It's bad." was dispatched. Verdict:
  GOOD wake. Trigger content is unrelated ordinary chatter (floor/slippery)
  and the follow-up is terse/ambiguous too, but a real follow-up arrived and
  dispatched -- per the ground-truth rule this is strong evidence of a
  wanted wake regardless of topic, same shape as the many other consumed
  pool-match entries below. No tuning change -- consumed pool wakes
  continue to show no bad pattern even on off-topic content.

- 2026-07-21: Trigger "But you can see the picture back and the computer.
  You can like Photoshop it and read it into the picture with you." (match
  kind: pool). Outcome: consumed -- follow-up "Why do you just hang it here
  often?" was dispatched. Verdict: GOOD wake. Trigger content is unrelated
  chatter (Photoshop/pictures) and the follow-up is garbled/unclear too, but
  a real follow-up arrived and dispatched -- per the ground-truth rule this
  is strong evidence of a wanted wake regardless of topic, same shape as the
  "non-profit"/"store"/"Great Dance" entries above. Note: this trigger also
  contains "computer" (the pool word flagged once before as bad-leaning on
  a timeout) -- but here it consumed cleanly, so no pattern change to that
  watch item; still just one bad-leaning data point on "computer", now
  alongside one good consumed one. No tuning change.

- 2026-07-21: Trigger "- Right, I ended up through my store every time. -
  Yeah, probably so." (match kind: pool). Outcome: consumed -- follow-up
  "Yeah, I think this is not great. That's a baseball fan." was dispatched.
  Verdict: GOOD wake. Both trigger and follow-up read as unrelated ordinary
  chatter (store, baseball) with nothing console-directed -- but per the
  ground-truth rule, a real dispatched follow-up is strong evidence of a
  wanted wake regardless of topic, same shape as the "non-profit"/billing
  entry above. No tuning change -- consumed pool-source wakes keep showing
  no bad pattern even when content is topically unrelated; the ground-truth
  signal (did dispatch happen) is doing its job.

- 2026-07-21: Trigger "The Great Dance!" (match kind: pool). Outcome:
  consumed -- follow-up "See you later." was dispatched. Verdict: GOOD wake.
  Trigger content is odd/unrelated (possibly a mis-hear of a book/movie
  title) and the follow-up is a closing remark, not console-directed
  content either -- but per the ground-truth rule, a real dispatched
  follow-up is strong evidence regardless of topic. No tuning change --
  single event, no prior pattern on this specific pool word to compare
  against.

(Newest entries first. Each entry: timestamp, what triggered the wake,
verdict, and any tuning change made -- or "no change, insufficient
pattern" if a single event isn't enough to act on.)

- 2026-07-21: Trigger "Like, hack a computer? She's so complicated. I broke
  so many things." (match kind: pool). Outcome: consumed -- follow-up
  "That's like several different people's jobs." was dispatched.
  Verdict: GOOD wake. Strong signal (real follow-up arrived), and this is
  the first-ever judged event, so no pattern to compare against either
  way. No tuning change -- single data point, and it's a positive one.

- 2026-07-21: Trigger "You know, it's nothing about Claude wanted me to
  plug it into an old TV. That's not, it did not guide me in that
  direction. This is, I'm swimming upstream." (match kind: exact).
  Outcome: timeout-with-leftover -- had content but nobody continued
  within the arm window. Verdict: GOOD wake, weak-timeout subtype. The
  utterance is literally about Claude/the console setup ("plug it into an
  old TV" describes this exact project) -- content-wise clearly directed
  at the console, just didn't get a follow-up in time (maybe Zach was
  mid-thought or moved on). Not evidence of a bad exact-match trigger --
  exact wake word matches are supposed to be low-friction by design. No
  tuning change -- single timeout on an exact match, content itself
  supports GOOD, and per Zach's framing single timeouts aren't actionable
  without a pattern. Watch for repeat timeouts specifically on exact-match
  wakes before considering raising friction there.

- 2026-07-21: Trigger "...system go through these steps like they'll just
  hack it together...on my actor I never knew the proper way but this
  thing does...if you want to do a professional job go go ahead..." (match
  kind: pool, matched word: "computer" -- inferred from context, "her
  computer"/"my actor" mid-ramble). Outcome: timeout-with-leftover -- had
  content, no follow-up came. Verdict: BAD wake (leaning). This is ordinary
  conversation about someone else's workflow/computer, not addressed to
  the console at all -- unlike the two prior entries, nothing here is
  about Claude or this project. "computer" is a generic word likely to
  appear constantly in unrelated speech, same false-positive risk as the
  book-title pool words. No tuning change yet -- single event on this
  word, need a pattern per Zach's rule. Watch specifically for repeat
  timeout-empty/timeout-with-leftover outcomes on pool word "computer" --
  if it recurs, raise cluster_min_by_source for dict-sourced words, or
  remove "computer" from wake-pool-dict.txt specifically (it's the most
  generic/collision-prone word in that list).

- 2026-07-21: Trigger "Last, hello." (match kind: pool). Outcome:
  consumed -- follow-up "Alright, I'm not getting the robot here. Wait,
  pull match arms." was dispatched. Verdict: GOOD wake. Follow-up is
  explicitly about the console not responding/waking properly -- directly
  addressed to the system, strong signal. No tuning change -- single
  positive data point, no prior pattern on "hello" or "last" as pool
  words to compare against.

- 2026-07-21: Trigger "Hello, hello Claude. Okay, so first we got to make
  the wake words a lot more sensitive." (match kind: exact). Outcome:
  consumed -- follow-up "It's just I'm losing you. I'm like I'm talking
  and I lose you when we're talking." was dispatched. Verdict: GOOD wake,
  clean case. Explicit "hello Claude" address plus a follow-up literally
  about wake reliability/missed utterances -- both trigger and follow-up
  are about the console itself. No tuning change -- exact-match wakes
  continue to show no bad pattern; this reinforces leaving exact-match
  friction alone. Note: Zach's own words here are a live feature request
  ("make the wake words more sensitive") and a complaint about dropped
  mid-conversation turns ("I lose you when we're talking") -- worth
  surfacing to him directly/next interaction, separate from this judge's
  tuning-file scope.

- 2026-07-21: Trigger "I guess that the friction is charming. Screenwriters.
  Okay, so that's the wake word. I would like to hear the beep immediately
  after the wake word. And I think the problem is here. Okay, I'm going to
  have to sell this on another machine. So just continue to dial in the
  wake word sensitivity." (match kind: pool). Outcome: timeout-with-leftover
  -- had content, no follow-up came. Verdict: GOOD wake. Content is
  explicitly meta -- Zach talking directly about the wake word system
  itself ("that's the wake word", "dial in the wake word sensitivity",
  wants a beep confirmation) -- unambiguously addressed to the console,
  just no follow-up utterance landed in the arm window. No tuning change --
  content-based GOOD wakes on pool matches don't indicate a bad pool word;
  this is a timeout on genuinely-directed speech, same shape as the
  "plug it into an old TV" exact-match entry above. Note: Zach's request
  for an audible beep confirming wake-word detection is a live feature
  ask, separate from tuning-file scope -- worth surfacing next
  interaction.

- 2026-07-21: Trigger "You can play a bell sound but that feels disowned.
  You want you want frauds? I did eventually What if this conversation
  Chris just had to stand in front of this TV and talk to you Right, you
  know, we can just have a little video console for the hit the talk"
  (match kind: pool, matched word: "console"). Outcome:
  timeout-with-leftover -- had content, no follow-up came. Verdict: GOOD
  wake (leaning), garbled STT. Despite heavy garbling ("frauds"? "hit the
  talk"?), the underlying content is clearly meta -- "stand in front of
  this TV and talk to you", "little video console" -- someone (Chris?)
  describing/demoing the console setup itself, same shape as the "plug it
  into an old TV" and "dial in the wake word sensitivity" entries above.
  No tuning change -- "console" pool word continues to show good-content
  timeouts, not noise false-positives (unlike "computer", which has one
  flagged bad-leaning event). Consistent with dict-sourced pool words
  needing less scrutiny than book-title words per the starting-values
  rationale.

- 2026-07-21: Trigger "Yeah, I'm cool, I'm funny, I'm cool." (match kind:
  fuzzy, source: dict). Outcome: timeout-with-leftover -- had content, no
  follow-up came. Verdict: BAD wake (leaning). Content is casual
  self-talk/banter with nothing about Claude, the console, or the wake
  system -- unlike the "console"/"TV"/"wake word" timeout entries above,
  there's no meta content here to redeem the timeout. Fuzzy dict matches
  are looser than exact/pool matches by design, so a content-free timeout
  here is a slightly stronger bad-wake signal than on exact/pool. No
  tuning change yet -- this is the first fuzzy/dict timeout with no
  redeeming content; need a pattern (repeat casual-chatter timeouts on
  fuzzy/dict matches) before raising FUZZY_CLOSE_RATIO or dict cluster_min.
  Watch specifically for more fuzzy-match wakes on ordinary banter.

- 2026-07-21: Trigger "Potato. Alright, now we're working. Now we're working."
  (match kind: pool). Outcome: consumed -- follow-up ". Alright, now we're
  working. Now we're working. in the quad system. Oh, God, give me a sign
  that you're getting this. Potato! This is me. This is me saying... trying
  to get a hold of. There you go." was dispatched. Verdict: GOOD wake, clean
  case. Follow-up is explicitly Zach trying to confirm the console is
  listening ("give me a sign that you're getting this", "trying to get a
  hold of") -- directly addressed to the system, plus "Potato" repeated on
  both sides suggests it may be a deliberate test/placeholder wake utterance
  rather than a mis-hear. No tuning change -- consistent with the broader
  pattern that consumed pool-source wakes keep showing no bad signal. First
  judged event on pool word "potato"; nothing to flag.

- 2026-07-21: Trigger "It's eight months a month per user through the
  non-profit, but I just have the non-profit pay for it." (match kind:
  pool). Outcome: consumed -- follow-up "We need your arts collective
  takeaway." was dispatched. Verdict: GOOD wake. Trigger content itself is
  unrelated to the console (billing/non-profit chatter), but a real
  follow-up arrived and dispatched -- per the ground-truth rule, consumed
  follow-up is strong evidence of a wanted wake regardless of trigger
  topic. No tuning change -- single consumed event, no pattern of bad
  pool-source wakes to weigh against it.
