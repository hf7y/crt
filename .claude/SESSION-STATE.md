# Session state (read this first, before STT-MECHANISM.md)

No live per-session state is tracked here day to day anymore — the backlog
moved to `gh issue list -R hf7y/crt` on 2026-08-14, and that is the real
record of what's open, blocked, and why. Check open issues and their
comments before assuming anything below, or in `HANDOFF.md`, is current.

**This file's entire prior contents (2026-07-19 through 2026-07-29, the
dexter/crt-vm and early-potato build-out) are archived at
`vault:crt/.claude/SESSION-STATE-20260829.md`** — read that for the blow-by-blow
history of that era. None of it describes the current topology: dexter now
hosts the Zaxon relay (reachable over tailscale, `provision/dexter/zaxon/`)
rather than a Windows+VirtualBox `crt-vm`, and `potato` (the Raspberry Pi)
is the live console — see `HANDOFF.md` and the open issues for what's
actually true today.

---

## 2026-09-18 — overnight run (Zach AFK, `/loop` self-paced)

**Read the issues first, as above.** This section is the running state of
one night, not a second backlog.

### What was wrong, and what fixed it

The room's LAN moved from `192.168.0.x` to `192.168.1.x` (potato is now
`192.168.1.247`; likely the same router event as crt#323). Two aliases were
pinned to the old subnet and both died silently:

- potato's `~/.ssh/config` `Host dexter` → `192.168.0.22`. Every brain
  escalation failed before sshd. **Fixed**: repointed at the tailscale
  address `100.107.253.56`, after verifying the host key fingerprints there
  were identical to the trusted `[192.168.0.22]:2223` entry. Backup:
  `~/.ssh/config.bak-20260918`.
- **mandark**'s own `Host potato` → `192.168.0.45`, still broken, left
  alone. Reach potato with
  `ssh -i ~/.ssh/vkv_deploy_key vkv@100.81.177.122`.

Whisper was never affected — it is addressed by tailscale IP already, and
potato's selfcheck read GREEN throughout. Two different things are called
"the brain": `/srv/whisper` on dexter (fine) and the `potato-claude` Claude
session (was gone).

Behind the dead alias, crt#140's report was still true: dexter had no
`~/crt-repo`, no `~/.local/bin/crt-brain-shell`, no tmux server.
**Rebuilt**: repo cloned to `~/crt-repo`, voice worktree `~/crt-brain`
(branch `voice`) created, shim reinstalled (senechal#924),
`potato-claude` started. `CAPTURE` and `SEND` both round-trip from potato.

### Landed

- **crt#343** (merged, `569828c`) — `crt-brain-session.sh` falls back to
  `$HOME/.local/bin/claude`. A non-interactive `ssh dexter '... ensure'`
  gets a PATH without `~/.local/bin`, so the restart path only ever worked
  from an interactive shell. Revert: `git revert 569828c`.
- **crt#346** (open) — `~/.crt/latency.log`, one line per utterance.

### Filed

- **crt#344** DECISION @zach — nothing paints on the CRT for ~2s after
  speech ends. Both mechanisms that could (`CRT_PREDICT_FLASH`,
  `CRT_SIDEBAND`) are off on potato and both alternatives are audio, not
  visual. The hard part is that at utterance close the console does not yet
  know it was addressed.
- **crt#345** — shortening the window itself. `TRAIL=0.8s` is about half of
  it and is the only cost not bounded by a model or a network.

### Measured (potato → dexter, 2026-09-18)

| stage | figure |
|---|---|
| tailnet RTT | 8ms |
| whisper, 3s clip | 0.72 / 1.32 / 0.72 / 0.76 s |
| `CRT_VAD_TRAIL` | 0.80s, fixed, paid before whisper starts |
| blind window | ~1.5–2.1s, before the brain's own thinking time |

Four synthetic clips. `latency.log` exists to replace them with real ones.

### The latency answer, measured (supersedes the table above)

Two of my own earlier readings on crt#345 were wrong and are corrected
there. What actually holds, measured from potato 2026-09-18:

| path | 3s clip | 10s | 20s |
|---|---|---|---|
| remote `/srv/whisper` on dexter | 0.74s | 0.79s | 0.87 / 1.41s |
| local `whisper-cli` on the Pi | **9.84s** | — | **9.94s** |

30-request burst against the remote: **0 failures, p50 0.82s, p90 0.86s.**
It does not scale with clip length and it is not slow.

The local fallback is flat at ~10s for a 3s clip and a 20s clip alike —
process start and model load paid per utterance, not decoding.
`CRT_WHISPER_SERVER_TIMEOUT` is 8s on top, for a server that hangs rather
than refusing.

`transcribe()` runs inside the capture loop, so nobody reads `arecord` for
either. The pipe holds 8.2s; a ~10s stall saturates it and only the newest
3s survives — a ~5s drop. potato's pane holds **606 such drops, median
5.0s, 47 minutes of audio discarded**, piled AT the cap rather than spread
out. So the drops are the fallback firing, not slow transcription.

They carry no timestamps, so they are historical — from a window that ended
when the console went quiet at 22:33 on 2026-09-17. Not a claim about now.

### Do not deploy to potato without Zach

`~/crt` there is **140 commits behind main** (205 files; `crt-stt-solo.py`
alone +74/-139), and the running process is 15 days old. Fast-forwarding
that onto a live console unattended is not a safe action, and crt#325's
pull timer would do the same thing on its first tick — measured onto that
issue, with the suggestion that the puller refuse a jump this size.

Consequence: crt#346 and crt#347 are merged but **not running on potato**.

### Next

1. crt#347 records `path=` per utterance. Once potato is current,
   `latency.log` answers how often the fallback fires — the one number
   still missing.
2. Do not touch `TRAIL`. It is 0.8s against a ~10s fallback; it is not
   where the time goes.
3. The real candidate for crt#345 is making the fallback cheap (a resident
   whisper.cpp instead of a per-utterance model load), or deciding that 10s
   of deafness is worse than dropping the utterance. Both are Zach's call.
4. crt#344 is Zach's call; do not guess a widget into the tube.
5. `potato-claude` has no persistence — a dexter reboot loses it and
   nothing restarts it. Noted on crt#343's DEFERRED.
