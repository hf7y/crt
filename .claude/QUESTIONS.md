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
