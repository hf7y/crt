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

## 2. The remote-Claude bridge — DECIDED 2026-07-28: **delete it**

**Zach's call, taken interactively via realisateur `/ideate` (on gardien)
on 2026-07-28, answering this section's own "do not defer this" — filed
here by realisateur once `check-project-busy crt` reported free.**

`bin/crt-remote-claude-bridge.py` + `bin/crt-mandark.sh` +
`crt-potato-tunnel.service` exist in their current shape for one reason,
stated in the bridge's own header: mandark has **no inbound network path**,
so the connection is a reverse tunnel initiated *outward* from mandark, and
potato holds no path into mandark at all. That is a security property
derived from the host being a laptop.

**The decision: delete, don't migrate.** With the brain on always-on dexter
and potato talking to it directly, `crt-mandark.sh`'s whole config surface
(`~/.crt/mandark.conf`) is dead weight. **This folds into FOCUS item 1's
existing "kill dead dexter/crt-vm code" sweep** rather than becoming its own
track — same sweep, one more corpse.

*Rejected, and why, so the fork survives its context:* **keeping the
reverse-tunnel shape** would have meant deliberately re-adopting "the brain
host has no inbound path" as a property worth having on dexter too. Not
chosen — the property was a consequence of mandark being an intermittent
laptop, and re-adopting it on an always-on box means paying its complexity
for a threat model nobody has argued for on its own merits. **Replacing it
with a direct service** was rejected as the worst of both: it keeps a
listening Claude bridge, and puts it on an always-on machine, which is a
real blast-radius increase for no gain once the reverse tunnel is gone
anyway.

The retirement half is filed to senechal (2026-07-28, "RETIREMENT IS A
CHANGE") — with the note that `crt-remote-claude-bridge.service` and
`crt-potato-tunnel.service` are *installed-but-inactive on mandark right
now*, which is exactly the state step 6 below warns against. Deleting the
code without removing those units would leave the corpse this decision
exists to clear.

The original framing, kept because it is still the right instinct: a
migrated-verbatim bridge documents a threat model that stopped being true,
which is how the next session inherits a wrong premise.

### BUILT 2026-07-28 — what "talking to it directly" turned out to mean

`# verified 2026-07-28 from potato's own shell via ssh dexter`

The decision above deleted a mechanism without naming its replacement, and
the gap was load-bearing: potato was still pointed at
`CRT_CLAUDE_REMOTE_PORT=8993`, i.e. at the bridge this section retires. The
replacement, now live:

- **`bin/crt-brain-shell.py`** (new, dexter-side) — the same two-verb
  protocol the bridge spoke (`CAPTURE`, `SEND`), driving the same
  `potato-claude` tmux session, but invoked by **sshd as a forced command**
  instead of by a listening socket. No daemon, no tunnel, no port.
- **`bin/crt-brain-session.sh`** (new, dexter-side) — asserts the tmux
  session exists. The bridge never had this: a human started `claude` by
  hand and nothing ever put it back when it died.
- **`bin/crt-secretary.py`** — new `CRT_CLAUDE_SSH_HOST` mode beside the
  old port mode. `brain_mode()` decides precedence in one place; ssh wins.
  `capture_pane()`/`send_to_claude()` remain the only two functions that
  know where the brain is, exactly as before.
- **`bin/crt-wake-router.py`** — `brain_configured_on()` + `probe_ssh()`,
  mirroring that precedence. Its probe sends a real `CAPTURE` rather than
  pinging, because the failure worth catching is a reachable dexter whose
  tmux session is dead — that state passes every cheaper check.
- **`tests/test_brain_ssh.py`** — 15 offline assertions, wired into
  `tests/run_tests.sh`. Covers the degrade contract and proves the SEND
  payload is never shell-interpreted rather than asserting it in a comment.

**Why this is not the "direct service" the section rejected.** That
rejection was about standing up a *listening Claude bridge* on an
always-on box — a new daemon with its own port and blast radius. This adds
no listener: it reuses the sshd dexter already runs, and the key is pinned
to one forced command with `restrict`. The tiny-protocol argument that
justified the original bridge is preserved intact; only the transport
changed. What genuinely did change is the **direction of trust** — potato
now has a path inward, narrowed to two verbs rather than eliminated. That
is a real difference from the mandark design and is stated plainly here
rather than buried, because it is the one property a future reader would
otherwise assume still holds.

**Trap found while wiring, worth more than the code.** dexter runs **two**
sshd: the Windows host on `:22`, the WSL2 instance holding the brain on
`:2223`. potato was authenticating against the wrong one, and the failure
mode was `Permission denied (publickey,password,keyboard-interactive)` —
indistinguishable from a missing or wrong key, with a *matching
fingerprint on both ends*. Anyone debugging "dexter won't take my key"
should check the port before touching credentials. potato's
`~/.ssh/config` now pins `Port 2223` with that reasoning inline.

**Still open after this**, and deliberately not done here: potato's key is
now confined to the brain protocol, so it **cannot run git** against
dexter. Section 3's repo repointing therefore needs a *second* key with a
git-shell restriction, not a reuse of this one. Noticed while wiring; a
single key doing both jobs would have quietly widened the forced command
back into general access, which is the whole thing this shape prevents.

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
   `PARKING-LOT.md`, `vault:crt/REFACTOR-ASSESSMENT.md`) and fix the ones that state
   host facts, not history. Leave the historical retrospectives alone.

## What is NOT part of this move

- The nightly self-repair timer on potato — installed and enabled
  2026-07-28, fires 04:15 local, unaffected by where the repo lives (it
  commits locally). It only *benefits* from step 3.
- crt-vm / the old VirtualBox target — already dead, and already queued for
  deletion under FOCUS item 1. Don't migrate corpses.
