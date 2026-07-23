# POTATO.md — potato, the repo↔mandark relationship, and wake routing

Current-topology doc for the live console. Read this alongside
`.claude/SESSION-STATE.md` (which has the day-to-day live state);
this file is the stable "how the pieces relate" reference.

## What potato is

- Raspberry Pi 3B+, quad Cortex-A53 @1.4GHz, **~905MB RAM** (1GB class),
  user `vkv`, project tree at `~/crt`. `ssh potato` (key auth, alias in
  mandark's `~/.ssh/config`).
- The real console hardware: composite/RF to a CRT (≈40×15), landline
  handset mic, USB audio ("KT USB Audio", capture only on `plughw:1,0`).
- Memory-constrained. Claude Code resident on potato was **~37% of RAM**
  (`ARCHITECTURE-REVIEW-2026-07-23.md`) — the whole reason the brain moved
  off-box. Keep potato lean.

## The potato art files

- **`potato-small.txt`** — Zach's braille-art potato. This is the
  **screensaver source**, rendered by `bin/crt-screensaver.py` (centered,
  dim cyan, breathing). This is now a load-bearing file, not decoration.
- **`potato_large.txt`** — **currently byte-identical to
  `potato-small.txt`** and referenced by nothing. Two cleanups for Zach
  (not guessed at unattended — it's your art):
  1. Naming is inconsistent: hyphen (`potato-small`) vs underscore
     (`potato_large`). Pick one convention.
  2. Either make `potato_large.txt` a genuinely larger/detailed variant
     (for an awake/attention screen), or delete it. Right now it's dead
     weight. `crt-screensaver.py --art <path>` will render whichever you
     point it at.

## Three directories, don't confuse them

The brain runs on mandark; potato's files live on potato. These are
**three different trees**:

| Path | Box | What it is |
|---|---|---|
| `~/Documents/Projects/crt` | mandark | This repo — the dev source of truth. Work happens here; scripts are scp'd out. |
| `~/crt` | potato | The live deploy target. **Own separate git history** (seeded by copy, not a clone). Files move here by hand (`scp`); always diff after copying. |
| `~/potato-crt` | mandark | An **sshfs mount of potato's `~/crt`** (`sshfs potato:/home/vkv/crt`). How Claude-on-mandark reads/writes potato's *real* files over SFTP. NOT this repo. |

## Where the brain runs (wake routing)

The design: **idle = screensaver, no brain resident (save RAM); on wake,
reach for a brain in priority order.**

```
idle  ── screensaver (potato-small.txt), NO Claude on potato
  │
  wake word ("potato"/pool match)
  │
  ▼
crt-wake-router.py decides:
  mandark ON + reachable   → REMOTE  (Claude on mandark, 0 RAM on potato) ★preferred
  mandark ON + unreachable → fall back: LOCAL if a local brain can run, else NONE
  mandark OFF              → LOCAL if available, else NONE
NONE = woken but no brain → short honest earcon/line, never silence.
```

- **Remote** path: potato's `stt` window escalates via
  `bin/crt-secretary.py` → `localhost:8993` → reverse tunnel → mandark's
  `bin/crt-remote-claude-bridge.py` → tmux session `potato-claude`. Potato
  never holds a Claude process. Tunnel is **mandark-initiated outbound**
  (`ssh -N -R 8993:localhost:8993 potato`); potato has no path *into*
  mandark, by design (see the bridge's threat-model header).
- **Local** path: the onsite fallback — a Claude on potato + local
  whisper, for lowest lag when mandark is unreachable. Highest RAM cost;
  only spun up on demand, never held at idle.

### The knobs

| Control | Where | Effect |
|---|---|---|
| `bin/crt-mandark.sh on\|off\|status` | run on potato | Flips remote routing; writes `~/.crt/mandark.conf`; `status` probes the live bridge. The one knob you touch. |
| `~/.crt/mandark.conf` | potato | Sourced by `crt-console.sh` at boot; sets `CRT_CLAUDE_REMOTE_PORT` (8993 = remote on, 0 = local/none). |
| `CRT_NO_IDLE_CLAUDE=1` | env for `crt-console.sh` | Window 0 becomes the screensaver instead of a resident Claude. Default off = historical always-resident layout (nothing regresses). |
| `bin/crt-wake-router.py [--json]` | potato | Prints the brain decision (`remote`/`local`/`none`). Pure + testable. |

## Remaining live wiring (needs potato hardware, not yet built)

The **decision brain, toggle, and screensaver exist and are offline-tested**.
What's left is the part that can only be verified on the physical Pi:

1. **A wake supervisor** that, on a real wake, calls `crt-wake-router.py`,
   and *acts* on `none`/`local`: switch window 0 away from the screensaver,
   and — on `local` — spawn an onsite Claude on demand (and tear it down
   after idle to reclaim RAM). Today `crt-secretary.py` already routes to
   the remote bridge fine; the missing glue is the on-demand local spin-up
   and the screensaver↔brain window swap.
2. **Local-brain readiness checks**: `crt-wake-router.local_claude_available()`
   currently only checks for creds — the supervisor should also gate on
   free RAM and whisper reachability before choosing `local`.
3. **Live verification** of the `CRT_NO_IDLE_CLAUDE` layout end-to-end on
   potato (wake → route → reply → back to screensaver), by ear.

Until #1 lands, run with the default layout (resident Claude) OR
`CRT_NO_IDLE_CLAUDE=1` + mandark ON — in that combination the console is
fully functional (remote brain) and mandark-down degrades to a short
honest reply, not a crash.
