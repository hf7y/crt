# Questions for the user

Running log, appended to (never overwritten or trimmed) by `/bug-sweep`
and `/nightly-batch` whenever something bigger than a routine tracker note
comes up. Clear an entry by deleting its line once you've actually read
and dealt with it; that's the only thing that should ever remove
something from this file.

- **2026-07-19 (design session): is the handset earpiece wired to `crt-vm`
  (guest-local ALSA) or only reachable via dexter's host-side audio
  bridge?** `crt-tts.py`'s `DEXTER_DEVICES` now includes `"handset"`
  alongside `"tv"`, meaning both currently route through
  `dexter-audio-server.py` over HTTP. That's fine for short TTS clips but
  rules out software sidetone (needs near-zero latency — see
  `SIDETONE.md`). Settle by checking `aplay -L` on the guest and tracing
  the earpiece cable once the VM is reachable.
  > [2026-07-20T17:03 zach] The handset is only reachable via dexter. Continue developing this as
  > two separate systems. The vm side that handles the interface and
  > specific assistant logic I'm looking for from the short term build is
  > separate from what dexter host-side controls: audio i/o, stt parsing.
  > This will allow for dexter host-side solutions to be moved into
  > the other crt ideas brewing (payphone simulator). When we go to bare
  > metal, these will both run on one machine together. But we'll
  > develop them as conceptually separate. This means the assistant side
  > needs a way to pass requests to dexter. How about a layer that does
  > different analog sounding bells (FM synthesis perhaps), passing 
  > data requests from the vm to dexter for sonification?

- **2026-07-23 (nightly-batch pass): is the handset play-while-capture
  finding real, by ear?** `bin/crt-earcon-loopback-test.py` (built this
  pass) measured the handset output (`plughw:1,0`, same USB device as
  the active mic capture) at 0.1x baseline signal vs the TV path's
  (`plughw:2,0`, separate device) 5.0x -- backwards from what physical
  proximity predicts, and strong evidence this USB adapter can't
  reliably play+record simultaneously. The tool's measurement is
  evidence, not proof. A likely fix is scaffolded but not deployed --
  `bin/setup-potato-audio-sharing.sh` (dmix/dsnoop sharing, no sudo
  needed) -- run it on potato, restart the `stt` window with
  `CRT_AUDIO_DEV=crtmic`, set `CRT_EARCON_HANDSET_DEVICE=crthandset`,
  then re-run `python3 bin/crt-earcon-loopback-test.py handset` to check
  if the ratio improves.

- **2026-07-23 (nightly-batch pass): is potato (Raspberry Pi 3 Model B+)
  the right long-term hardware?** Discovered live this pass -- weaker
  than the Pi 4/5-class hardware assumed in earlier research, 905MB RAM
  with real memory pressure observed (183MB free, active swap, load
  average 1.36). Vosk (tested live, small English model) wasn't
  dramatically faster than realtime on this specific box either. Not a
  question this pass should guess at -- flagging for a human decision on
  whether to keep tuning around this hardware or consider an upgrade.

- **2026-07-23 (nightly-batch pass): should `CRT_WAKE_ARM_ENABLED`/
  `CRT_WAKE_JUDGE_ENABLED` be turned on?** Both new (this pass), both
  default OFF, both NOT hardware-verified. `bin/crt-wake-arm.py`
  implements the arm-window state machine that both closes the
  sticky-conversation-window gap AND finally wires crt-wake-judge.py's
  autonomous tuning judge to a real trigger. Needs a live session to
  confirm the default `CRT_WAKE_ARM_SECS=12` (how long a follow-up
  window stays open) actually feels right before either flag becomes the
  default.


- **2026-07-27 (realisateur, via `/ideate`): the six `ssh potato` auth-rejected entries below (2026-07-24, cycles 5-8) are CLEARED — superseded by a working access path.** Tonight's reconciliation session reached potato successfully via `vkv_deploy_key`, not this account's default key; Zach confirmed (2026-07-27 `/ideate`) the default-key gap isn't worth tracking separately since a working credential already exists. If default-key access from this account becomes load-bearing later, re-open as a fresh dated entry rather than reviving these.

- **2026-07-24 (nightly-batch, 7th cycle today): `~/reports/crt` write
  access is fixed** -- `id`/`groups` now show `zach` IS a member of
  `vaporwave-reports` (was missing as of the 2026-07-23 report). Removed
  the stale question above about it; confirmed writable with a real
  touch+rm this cycle.

- **2026-07-24 (nightly-batch, this cycle): offline-safe backlog appears
  exhausted for now.** Checked every item in `.claude/FOCUS.md`'s
  "PRIORITIZED BATCH BACKLOG" and the stability-milestone bar itself:
  all 4 bar items are code-complete and blocked only on the `ssh potato`
  question above; ranked-backlog items 1/2/3/5/5b/6 are explicitly
  PARKED by the milestone; item 5c (test-coverage gaps) and item 7
  (handset 3-pin switch writeup) both landed earlier today
  (`e8d6aba`/`550b70c`, `9cc07a1`); the 2026-07-24 16:12 "audio tests
  outputting to mandark card" note was also already fixed today
  (`108406f`). The remaining scheduler notes at the top of FOCUS.md
  (potato-game-as-boot-mode, column-width investigation, passwordless
  sudo, textart.sh potato-art scrape) are all either `[hw]` or outside
  the declared stability-milestone focus, so left deferred per this
  skill's own scoping instruction rather than implemented as
  easy-but-off-focus wins. If this keeps recurring, worth either
  broadening the milestone bar or registering a new offline-safe batch
  item explicitly.

- **2026-07-28 (realisateur, Zach-directed, filed for later): stand up a second whisper server on dexter, as a failover peer to mandark's.** During tonight's live-verify pass, `crt-stt-solo.py` on potato logged intermittent `TRANSCRIPTION FAILED ... gave no answer` against `CRT_WHISPER_SERVER=http://192.168.0.27:8991` — that IP is **mandark** (`crt-whisper-server.service`, confirmed healthy, every `/transcribe` in its own logs returned 200 for the exact window potato saw failures), so the fault is network-level between potato and mandark, not the whisper server being down. `bin/dexter-whisper-server.py` already exists in this repo (built 2026-07-19, verified working live back then) — Zach's direction: don't build this now, just record it as the next concrete step so potato can fail over to dexter if the mandark path drops again. Not required for the current milestone bar (mandark's server is the one actually in use and it's healthy); this is redundancy, not a blocker.

- **2026-07-28 (realisateur, live full-loop test): the potato<->mandark network flakiness is a shared root cause, not two separate bugs.** During the same session's full-loop live test (wake -> STT -> bridge -> mandark brain -> reply), most utterances after the first hit `wait_for_claude_reply`'s honest "unobserved" path (`I sent that to Claude, but I lost my view of the answer partway through`) even though the bridge process and reverse tunnel were both confirmed alive and unerrored throughout. This is the same shape as the whisper-transcribe failures logged in the entry above (same network path, potato<->mandark, both HTTP and the raw bridge TCP socket affected) -- strengthens the case that this is one underlying link-reliability issue, not independent app bugs in two different scripts. Not investigated further this session (no packet capture, no `mtr`/ping-loss measurement taken) -- worth an actual network-level diagnosis (packet loss %, whether it's the tailscale/LAN path, whether the reverse tunnel's `ServerAliveInterval` is masking drops) before deciding whether the dexter-whisper-failover item above is sufficient or whether the bridge itself needs its own retry/reconnect hardening.

- **2026-07-28 (realisateur, Zach-directed, filed for later, PARKED): dual-output earcons (both handset AND HDMI simultaneously) with per-earcon-type device configuration.** Right now `CRT_EARCON_DEVICE` is one global toggle read by both `crt-stt-solo.py`'s and `crt-secretary.py`'s `play_earcon()` calls -- either everything goes to the quiet handset or everything goes to the room-wide HDMI/RF-converter path, and every earcon NAME (`addressed`/`control`/`thinking`/`oops`/etc.) shares that one device. Zach's ask: play some or all earcons to BOTH devices at once, and let the device choice vary per earcon name (e.g. "addressed" room-wide so anyone hears the console woke up, "thinking" quiet/handset-only so it's not a constant room noise during normal use). Not required for the current milestone bar (the loop works either way); this is a UX-shaping decision Zach should make deliberately once there's been more live listening time with the current single-toggle version, not guessed at now. Shape sketch for whenever it's picked up: a per-name device map (dict, default falls back to `CRT_EARCON_DEVICE`) passed into both `play_earcon()` call sites, plus a "both" pseudo-device that fires two `crt-earcon.sh` invocations.

- **2026-07-28 (realisateur, live-verify): trivia-fact enrichment pipeline built and scrape stage proven live -- distill stage needs a Gemini key.** `bin/crt-book-facts-batch.py`'s scrape stage ran live against all 5 real registered books: "Lolita" pulled 6 real candidate sentences from Wikipedia's public API, three others correctly cached an empty result (no exact-title match), nothing errored. The AI/distill stage (batched, ~3 curated facts per book) is built, tested, and wired to fire automatically from a live scan once >=5 books lack facts_json (never per-scan) -- but potato has no `CRT_GEMINI_API_KEY`/`~/.crt/gemini.key` configured, so it currently loudly no-ops every time it's triggered. Needs Zach to provision a Gemini key (same mechanism `install.sh` already writes for the existing question-generation Gemini path) before the distill half can actually run.

- **2026-07-28 (dexter move, filed at close): what happens to the
  remote-Claude bridge on an always-on host?** `crt-remote-claude-bridge.py`
  + `crt-mandark.sh` + `crt-potato-tunnel.service` are shaped the way they
  are for one reason, stated in the bridge's own header: mandark has no
  inbound network path, so the connection is a reverse tunnel initiated
  outward. On always-on dexter that rationale stops being true. Three
  honest options: keep the reverse-tunnel shape *deliberately* (the
  property is still worth having), replace it with a direct listening
  service (simpler, but a real blast-radius change), or delete it entirely
  and fold `~/.crt/mandark.conf` into FOCUS item 1's dead-code sweep.
  Migrating it verbatim is the one option that's wrong — it would
  fossilize a threat model that no longer holds. See `DEXTER-MOVE.md` §2
  (`51f7346`).
  > (answer inline here)

- **2026-07-28 (dexter move, filed at close): does potato get PUSH access
  to the dexter-hosted repo, or stay pull-only?** Repointing potato's
  `origin` at something it can actually reach is the move's real
  deliverable — today's session proved potato has never once been able to
  fetch. Pull-only already fixes the drift and lets the nightly self-repair
  pass pull. Push access is a separate blast-radius decision (an autonomous
  unit writing to the shared repo) that you reserved earlier, modeled on
  `svc-vaporwave`. Flagging it because the wiring step is where someone
  would quietly grant both at once. See `DEXTER-MOVE.md` §3 (`51f7346`).
  > (answer inline here)

- **2026-08-06 (nightly-batch): arm-window timing-reference fix landed, needs a live retry to actually answer the `CRT_WAKE_ARM_SECS` question above.** The 2026-07-28 milestone entry (top of `FOCUS.md`) found every real follow-up attempt arriving 16s+ after its wake word, past the 12s window, and couldn't tell how much of that was real speaking pace vs. transcription/network lag eating into the window before it was even logged. Root cause found and fixed tonight: the window's clock was starting from when `emit()` got called (after `transcribe()` returned) instead of from when the person actually stopped talking (VAD-end, before `transcribe()` runs) — so slower-than-usual transcription was silently shrinking the real budget on a per-utterance basis. `bin/crt-stt-solo.py`/`bin/crt-wake-arm.py` fixed, tested (`tests/test_wake_rearm_ceiling.py`), full suite green. This does NOT answer whether 12s is the right number for natural pacing — it removes a confound that was making the question unanswerable. `ssh potato` failed to resolve from this box tonight, so no live retry happened. Needs: a live wake→pause→follow-up attempt on potato with this fix deployed, to see whether the 16s+ gap shrinks toward 12s (latency was the cause) or stays wide (12s itself is too tight).
  > (answer inline here)

- **2026-08-06 (nightly-batch): `ssh potato` isn't flaky DNS -- potato has never been joined to the tailnet this runner uses, which is why every unattended cycle's live-verify attempt fails the same way.** Chased the "Could not resolve hostname potato" failure one level further than previous cycles did (which each just logged the symptom and moved on, per this skill's own don't-debug-the-whole-cycle policy). This box (`monkey` in `tailscale status`) is on a live tailnet alongside `dexter`, `mandark`, and `homeassistant` -- all three resolve and respond to a TCP SSH handshake (`dexter`/`mandark` currently fail at host-key verification, a separate and untouched issue, not attempted further since that's outside this skill's granted scope). `potato` is not in `tailscale status`'s peer list at all -- not offline, not unseen, simply never a node on this tailnet -- and its LAN IP (`192.168.0.45` per `POTATO.md`/`FOCUS.md`) is naturally unreachable from a box that isn't on that LAN. So this isn't a transient resolution hiccup that might clear up next cycle: **no network path from the nightly-batch runner reaches potato at all, structurally, until potato itself joins the tailnet** (`tailscale up` on potato, one-time, needs Zach's hands or at minimum an auth-key decision). Every "ssh potato was unreachable tonight" note in this file/FOCUS.md going back to 2026-07-23 is almost certainly the same root cause, not N separate flakes. If/when potato joins the tailnet, the existing `Host potato` alias this skill's own doc describes (in the persistent zach@mandark account, not this disposable runner) may need its `HostName` re-pointed at the tailnet address/MagicDNS name rather than the raw LAN IP.
  > (answer inline here)
