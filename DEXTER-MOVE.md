# Moving crt off mandark and onto dexter

Zach's decision, 2026-07-28: this project's home — the git repo it pushes
to, and the always-on services it depends on — moves from `mandark` (a
Windows laptop that comes and goes) to `dexter` (always on). Work to be
done with `gardien`. This file is the checklist and, more importantly, the
**inventory of what is actually load-bearing on mandark right now**, probed
live rather than recalled.

The premise that matters: several pieces of this project are shaped around
"mandark is intermittent and has no inbound network path." Once the host is
always-on and reachable, those shapes are not just movable — some of them
stop being necessary. Moving them verbatim would fossilize a rationale that
no longer holds.

## 1. Live inventory of mandark's crt footprint

`# verified 2026-07-28 via systemctl is-active / ss -ltn / git remote -v / crontab -l`

| What | State | Notes |
|---|---|---|
| `/home/zach/git-remotes/crt.git` (bare) | 16M | the `origin` every clone pushes to |
| `crt-whisper-server.service` | **ACTIVE**, listening `0.0.0.0:8991` | LAN STT server; `ufw` port opened. The one genuinely always-on dependency living on a laptop. |
| `crt-remote-claude-bridge.service` | installed, inactive | port 8993 |
| `crt-potato-tunnel.service` | installed, inactive | `ssh -N -R` out to potato |
| crt crontab entries | none | `crontab -l` has no crt lines |
| crt user systemd units | none | only `synergy.desktop` in autostart, unrelated |
| scheduler pacing entry | already `_paced.dexter.conf` | crt is paced from dexter already, NOT mandark |

Installers for those units are `bin/setup-mandark-whisper-persistence.sh`
and `bin/setup-mandark-remote-claude-persistence.sh` — read both before
recreating anything; the second one carries a self-flagged hardcoded-PID
hack and a port (8993) duplicated in three places with no single source.

Not in the table because it is gone: `crt-vm_claude_creds.json` (live OAuth
tokens, untracked, repo root) was **deleted 2026-07-28** on Zach's
instruction rather than migrated. If a future session finds it again,
something restored it from a backup — do not carry it to dexter.

## 2. Decide the remote-Claude bridge's fate BEFORE moving it

`bin/crt-remote-claude-bridge.py` + `bin/crt-mandark.sh` +
`crt-potato-tunnel.service` exist in their current shape for one reason,
stated in the bridge's own header: mandark has **no inbound network path**,
so the connection is a reverse tunnel initiated *outward* from mandark, and
potato holds no path into mandark at all. That is a security property
derived from the host being a laptop.

On an always-on, reachable dexter, the honest options are:

- **Keep the reverse-tunnel shape** — deliberately, because "the brain host
  has no inbound path" is still a property worth having, not because it was
  inherited.
- **Replace it with a direct service** — simpler, but that is a real
  blast-radius decision (a listening Claude bridge on an always-on box) and
  needs Zach in the loop, same class as potato's push-access question.
- **Delete it** — if the brain runs on dexter and potato talks to it
  directly, `crt-mandark.sh`'s whole config surface (`~/.crt/mandark.conf`)
  is dead weight. FOCUS item 1 is already a "kill dead dexter/crt-vm code"
  sweep; this would fold into it.

Do not defer this past the move. A migrated-verbatim bridge documents a
threat model that stopped being true, which is how the next session
inherits a wrong premise.

## 3. Potato's `origin` is the actual deliverable

Today potato's `~/crt` has `origin = /home/zach/git-remotes/crt.git` — a
**local filesystem path that exists only on mandark**. Potato therefore
cannot fetch or pull, ever, and has silently drifted before (2026-07-28: 5
commits behind with a file-level copy layered on a stale HEAD; reconciled by
`git bundle` over `scp`, see the commit history and the migration memory).

Direction of travel today is one-way and works: mandark has a `potato`
remote (`ssh://potato/home/vkv/crt`) and `git fetch potato` succeeds — so
potato's nightly self-repair commits are recoverable, they just have to be
pulled rather than pushed.

**The move fixes this or it wasn't worth doing.** After the move potato's
`origin` must point at a dexter-hosted repo it can reach, so that:

- `git pull` on potato works unattended (nightly self-repair currently
  commits into a repo with nowhere to send anything);
- the reconciliation dance (bundle + scp + stash + ff-merge) stops being
  the sync mechanism.

Whether potato gets **push** access is a separate, still-open decision Zach
has explicitly reserved (service-user identity modeled on `svc-vaporwave`,
likely pull-only at first). Pull-only still fixes the drift; do not quietly
grant push while wiring the URL.

## 4. Order of operations

1. Stand up the bare repo on dexter; push `main` from mandark; verify
   `git log -1` matches on both sides before anything else changes.
2. Repoint this working checkout's `origin`, verify a round-trip
   push/fetch.
3. Repoint potato's `origin` to the dexter URL; verify `git fetch` **from
   potato** (this is the whole point — a URL that is merely typed is not a
   fix; see how the current bogus one survived months).
4. Move `crt-whisper-server` to dexter (unit + `ufw` port); repoint whatever
   points at `mandark:8991`; confirm STT actually transcribes on potato,
   not merely that the port answers.
5. Settle §2's bridge decision; install, or delete, accordingly.
6. Retire the mandark units that are now duplicated — **actually remove
   them**, don't leave them installed-but-inactive, which is exactly the
   state `crt-remote-claude-bridge` / `crt-potato-tunnel` are in today.
7. `notify-senechal` for every machine-scoped change on both hosts — units
   installed on dexter AND units retired on mandark. Retirement is a
   change; a stale senechal entry pointing at a dead mandark unit is the
   failure this protocol exists to prevent.
8. Grep the docs for `mandark` (currently ~10 files: `POTATO.md`,
   `STT-MECHANISM.md`, `SELF-REPAIR.md`, `AUDIO-ROUTING.md`, `HANDOFF.md`,
   `SECRETARY.md`, `MORNING-REPORT-PRESENTATION.md`, `AUDIO-DEBUG.md`,
   `PARKING-LOT.md`, `REFACTOR-ASSESSMENT.md`) and fix the ones that state
   host facts, not history. Leave the historical retrospectives alone.

## What is NOT part of this move

- The nightly self-repair timer on potato — installed and enabled
  2026-07-28, fires 04:15 local, unaffected by where the repo lives (it
  commits locally). It only *benefits* from step 3.
- crt-vm / the old VirtualBox target — already dead, and already queued for
  deletion under FOCUS item 1. Don't migrate corpses.
