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

### READ THIS FIRST: the brain on dexter is signed out

    ● Login expired · Please run /login

**Needs Zach, on dexter.** `tmux attach -t potato-claude`, run `/login`,
detach. Nothing on potato or in this repo can do it.

Everything *around* it is genuinely fixed — the ssh path, the forced
command, the tmux session, the voice worktree — and `SEND` returns `OK`
because `tmux send-keys` succeeds. **No utterance has been answered.** I
reported the brain alive on crt#140 before noticing; corrected there.

It was visible in the room and missed: `~/.crt/gate.log`, 06:53 today —
"Potato, can you reach your brain?" — asked of a console I had just called
working.

crt#348 teaches `crt-brain-session.sh status` to report it. It had slipped
every check because it is **not a modal**: a signed-out Claude renders an
ordinary idle prompt with the error in the scrollback, so `parked_reason()`
passes it and `CAPTURE` returns a healthy body.

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

### Next

1. Merge crt#346, then deploy to potato and restart the `stt` window so the
   log starts filling. Nothing is deployed to potato yet.
2. Read a night of `latency.log` before touching `TRAIL` (crt#345).
3. crt#344 is Zach's call; do not guess a widget into the tube.
4. `potato-claude` has no persistence — a dexter reboot loses it and
   nothing restarts it. Noted on crt#343's DEFERRED.
