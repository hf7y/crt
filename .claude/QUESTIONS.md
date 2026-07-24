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


- **2026-07-24 (nightly-batch, 5th cycle today): `ssh potato` regressed
  from "reachable but auth-rejected" to fully unresponsive.** Cycles 2-4
  today all got `Permission denied (publickey,password)` from
  `vkv@192.168.0.45` (host up, wrong key). This cycle got a bare
  connection timeout on both SSH and `ping` to that same IP — no answer
  at all, a strictly worse state (host likely off-network, powered down,
  or re-addressed again). The stale `~/.ssh/config` `Host potato` entry
  question from cycles 2-4 still stands; now compounded by potato
  possibly being offline outright. This blocks all live verification of
  bar items 2/3/4 in `.claude/FOCUS.md`'s stability milestone.

- **2026-07-24 (nightly-batch, 6th cycle today): correction to the 5th
  cycle's "potato may be off-network" conclusion.** This cycle's
  environment has no route to 192.168.0.0/24 at all (ip route only
  shows a 10.129.176.0/20 link) -- a subnet sweep from here can't
  distinguish "potato is down" from "this box just can't reach that LAN
  this session" (e.g. no VPN/tunnel active). The bare-timeout result is
  real but its cause is now less certain than the 5th cycle's report
  implied. Needs a human check from a machine actually on potato's LAN
  (or with an active tunnel to it) before concluding potato itself is
  offline.

- **2026-07-24 (nightly-batch, 7th cycle today): potato is back to
  "reachable but auth-rejected"** -- `ip route` this session shows
  `192.168.0.0/24` reachable again (unlike the 6th cycle's no-route
  session), and `ssh potato` gets `Permission denied
  (publickey,password)` from `vkv@192.168.0.45`, the same failure shape
  as cycles 2-4, not the bare timeout of cycles 5-6. This resolves the
  6th cycle's open question in favor of "potato itself is likely fine,
  just not accepting this account's key" -- the real, still-open blocker
  is `~/.ssh/config`'s `Host potato` entry (wrong user/key, or the
  host's `authorized_keys` no longer has this account's public key).
  Not something to brute-force blind; needs Zach to either add
  `~/.ssh/id_ed25519.pub` to potato's `authorized_keys` directly, or
  confirm the right user/key to use here.

- **2026-07-24 (nightly-batch, 7th cycle today): `~/reports/crt` write
  access is fixed** -- `id`/`groups` now show `zach` IS a member of
  `vaporwave-reports` (was missing as of the 2026-07-23 report). Removed
  the stale question above about it; confirmed writable with a real
  touch+rm this cycle.
