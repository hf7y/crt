# POTATO.md — potato, the repo↔mandark relationship, and wake routing

Current-topology doc for the live console. Read this alongside
`.claude/SESSION-STATE.md` (which has the day-to-day live state);
this file is the stable "how the pieces relate" reference.

## What potato is

- Raspberry Pi 3B+, quad Cortex-A53 @1.4GHz, **~905MB RAM** (1GB class),
  user `vkv`, project tree at `~/crt`. `ssh potato` (key auth, alias in
  mandark's `~/.ssh/config`).
- The real console hardware: **HDMI out → RF converter → CRT** (≈40×15,
  landline handset mic, USB audio ("KT USB Audio", capture only on
  `plughw:1,0`). **Confirmed 2026-07-28, live, by ear (Zach): HDMI audio
  (`aplay -D plughw:2,0`, card 2 `vc4-hdmi`) DOES reach the room** through
  that converter — this is the room-wide alert path, not a dead port.
  Earlier phrasing here ("composite/RF to a CRT") was read as "HDMI is
  disconnected from the real signal chain" during the same day's earcon
  work and cost real time chasing whether anything was even plugged in —
  it wasn't wrong about the RF/CRT part, just silent about HDMI being the
  thing feeding the converter. `crt-earcon.sh --device tv` and
  `CRT_EARCON_DEVICE=tv` (potato's `~/.bash_profile` testing default,
  toggle back to `handset`) are this path, live and correct.
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

The brain runs on **dexter** (since 2026-07-28); potato's files live on
potato. These are **four different trees** — the fourth arrived with the
dexter move, and the count in this heading has been wrong before:

| Path | Box | What it is |
|---|---|---|
| `~/Documents/Projects/crt` | mandark | This repo — the historical dev source of truth. Still where `origin` lives (`~/git-remotes/crt.git`) until DEXTER-MOVE.md section 3 lands. |
| `~/crt-repo` | dexter | Working checkout on the **brain host**, added 2026-07-28. Where the SSH-brain work was done. Also the default cwd of the `potato-claude` session, so the console's brain can read its own project. |
| `~/crt` | potato | The live deploy target. Real `git clone` since 2026-07-27, but its `origin` is a **mandark-only filesystem path**, so it still cannot `git pull` — see DEXTER-MOVE.md section 3. |
| `~/potato-crt` | mandark | An **sshfs mount of potato's `~/crt`** (`sshfs potato:/home/vkv/crt`). How Claude-on-mandark reads/writes potato's *real* files over SFTP. NOT this repo. |

## Where the brain runs (wake routing)

**Changed 2026-07-28: the brain host is now `dexter`, reached over plain
SSH. The mandark reverse tunnel is retired.** What follows describes the
live topology; the old one is kept at the bottom of this section because
its threat model explains why the current shape looks the way it does.

The design is unchanged: **idle = screensaver, no brain resident (save
RAM); on wake, reach for a brain in priority order.**

```
idle  ── screensaver (potato-small.txt), NO Claude on potato
  │
  wake word ("potato"/pool match)
  │
  ▼
crt-wake-router.py decides:
  dexter configured + reachable   → REMOTE  (Claude on dexter, 0 RAM on potato) ★preferred
  dexter configured + unreachable → fall back: LOCAL if a local brain can run, else NONE
  nothing configured              → LOCAL if available, else NONE
NONE = woken but no brain → short honest earcon/line, never silence.
```

- **Remote** path: potato's `stt` window escalates via
  `bin/crt-secretary.py` → `ssh dexter` → dexter's
  `bin/crt-brain-shell.py` (an sshd **forced command**) → tmux session
  `potato-claude`. Potato never holds a Claude process. No tunnel, no
  listening service, no daemon to drop.
- **What the key can do, and only that.** potato's key is pinned in
  dexter's `authorized_keys` with `command="…/crt-brain-shell",restrict`.
  It gets the two-verb protocol (`CAPTURE`, `SEND`) against one named tmux
  session — no shell, no sftp, no port forwarding. Verified from potato
  2026-07-28: a shell request is refused and logged, sftp and `-L`
  forwarding both fail, `CAPTURE` works.
- **Direction of trust changed, deliberately.** The old design gave potato
  *no* path into the brain host, because that host was a personal laptop.
  dexter is a dedicated always-on box that already runs sshd, so potato
  now connects inward — narrowed to one forced command rather than
  eliminated. This was the fork chosen on 2026-07-28; see DEXTER-MOVE.md
  section 2 for the two rejected alternatives.
- **Local** path: unchanged — the onsite fallback, a Claude on potato +
  local whisper, for when dexter is unreachable. Highest RAM cost; only
  spun up on demand, never held at idle.

> **Port 2223, not 22.** dexter runs two SSH daemons: the Windows host
> answers `:22`, and the WSL2 instance that actually holds the brain
> answers `:2223`. Connecting to the wrong one fails as
> `Permission denied (publickey…)`, which reads exactly like a missing
> key and cost a debugging detour on 2026-07-28. potato's
> `~/.ssh/config` pins `Port 2223`; if the brain ever looks
> "unauthorized", check the port before regenerating any keys.

### The knobs

| Control | Where | Effect |
|---|---|---|
| `CRT_CLAUDE_SSH_HOST=dexter` | potato, `~/.crt/brain.conf` | **The knob.** Sourced by `crt-console.sh` at boot; routes escalations to dexter over SSH. Unset = local/none. |
| `bin/crt-brain-session.sh ensure\|status\|restart` | run on dexter | Asserts the `potato-claude` tmux session is alive. `status` is the honest health check — it refuses to call a trust-prompt-parked Claude "UP". |
| `bin/crt-wake-router.py [--json]` | potato | Prints the brain decision (`remote`/`local`/`none`). Pure + testable. `--json` now carries `brain_mode`/`brain_target`. |
| `CRT_NO_IDLE_CLAUDE=1` | env for `crt-console.sh` | Window 0 becomes the screensaver instead of a resident Claude. Default off = historical always-resident layout (nothing regresses). |
| `bin/crt-mandark.sh on\|off\|status` | potato | **RETIRED** along with the bridge — kept only until the section-2 deletion sweep runs. Do not wire anything new to it. |

<details><summary>Retired: the mandark reverse-tunnel topology (2026-07-23 → 2026-07-28)</summary>

potato's `stt` window escalated via `crt-secretary.py` →
`localhost:8993` → reverse tunnel → mandark's `crt-remote-claude-bridge.py`
→ tmux session `potato-claude`. The tunnel was **mandark-initiated
outbound** (`ssh -N -R 8993:localhost:8993 potato`), so potato had no path
*into* mandark at all. That was not a preference — mandark is a personal
dev laptop that has never run sshd, and giving potato a way in was flagged
as a real vulnerability. The shape was correct for that host; it stopped
being necessary when the brain moved to a box that is always on and
already accepts SSH. Recorded here so nobody re-derives the tunnel from
first principles and assumes it was arbitrary.

</details>

## Remaining live wiring (needs potato hardware, not yet built)

The **decision brain, toggle, and screensaver exist and are offline-tested**.
What's left is the part that can only be verified on the physical Pi:

1. **A wake supervisor** that, on a real wake, calls `crt-wake-router.py`,
   and *acts* on `none`/`local`: switch window 0 away from the screensaver,
   and — on `local` — spawn an onsite Claude on demand (and tear it down
   after idle to reclaim RAM). Today `crt-secretary.py` already routes to
   dexter over SSH fine; the missing glue is the on-demand local spin-up
   and the screensaver↔brain window swap.
   *Still the top item after the 2026-07-28 dexter move — the transport
   changed underneath it, the missing glue did not.*
2. **Local-brain readiness checks**: `crt-wake-router.local_claude_available()`
   currently only checks for creds — the supervisor should also gate on
   free RAM and whisper reachability before choosing `local`.
3. **Live verification** of the `CRT_NO_IDLE_CLAUDE` layout end-to-end on
   potato (wake → route → reply → back to screensaver), by ear.

Until #1 lands, run with the default layout (resident Claude) OR
`CRT_NO_IDLE_CLAUDE=1` + mandark ON — in that combination the console is
fully functional (remote brain) and mandark-down degrades to a short
honest reply, not a crash.
