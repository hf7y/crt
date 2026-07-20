# VM-resident jobs: a second autonomy tier, separate from the scheduler's engine

`.claude/commands/nightly-batch.md` (the existing, working Tier 2 batch,
registered in `schedule/crt.conf`) explicitly cannot reach crt-vm or
dexter — it runs in a disposable clone on mandark, code-only, by design.
That leaves every hardware-shaped item in `FOCUS.md`'s backlog
permanently out of reach of any autonomous job, until now.

**This session's answer**: a second, independent job that runs directly
*on* crt-vm — not through the mandark scheduler's clone-and-run engine at
all, just a plain systemd timer firing `claude -p` locally, in the real
checkout, with real mic/display/printer access. Built this session, ready
to install, **not yet installed or run** (no VM access this session).

## The three tiers, now
1. **Tier 1/2 (mandark, existing)** — `nightly-batch.md` / bug-sweep,
   disposable clone, code-shaped work only, already registered and
   working via `schedule/crt.conf`.
2. **VM-resident (new, this session)** — `.claude/commands/
   vm-hardware-check.md` + `systemd/crt-vm-hardware-check.{service,timer}`.
   Runs on crt-vm itself, once/day, with real hardware. Scope is
   deliberately narrow: **verify, don't build** — run the offline test
   suite for real, check device presence, exercise (not judge) the audio
   scripts, report honestly. Not a general-purpose autonomous dev job;
   trying to make it one would just re-invent Tier 1/2 with worse
   isolation (no disposable clone, real hardware at stake).
3. **Interactive (this conversation, and future ones like it)** — design,
   judgment calls, anything needing a human's ear/eye/decision.

## Getting the VM's reports somewhere a human actually looks
`morning-report.sh` (mandark) only ever reads
`~/reports/<project>/LATEST.md`. The VM-resident job writes its own
`~/reports/crt/LATEST.md`, but that file lives **on crt-vm**, invisible to
mandark until something pulls it over. `bin/crt-sync-vm-reports.sh`
(this session) does that pull, via the documented `ssh -p 2222
zach@dexter.local` access — but deliberately writes into
`~/reports/crt/vm/` on mandark, **not** overwriting
`~/reports/crt/LATEST.md` directly, because that file is also written by
this session's own `bin/crt-report.sh` from interactive work, and a blind
overwrite would silently clobber whichever one ran more recently.

**This means the VM's reports don't automatically show up in
`morning-report.sh`'s output yet** — that's the real open item, and it
has two honest options, not yet decided:
1. Teach `morning-report.sh` (shared scheduler infra, used by every
   project, not just crt) to also check a project's `reports/<project>/
   vm/LATEST.md` if present. Bigger blast radius — touches shared code
   other projects depend on.
2. Have `crt-sync-vm-reports.sh` (or a wrapper around it) merge the VM's
   content into `~/reports/crt/LATEST.md` as a clearly-labeled section,
   rather than overwriting. Smaller blast radius, crt-only, some
   merge-logic complexity.
Leaning toward option 2 (contained to this project), but not implemented
— flagging rather than guessing, since it touches how reports are
presented, a judgment call worth Chris's input.

## Wiring the pull into the scheduler (rather than a bare cron line)
`crt-sync-vm-reports.sh` needs to run periodically FROM mandark. Rather
than a bare personal crontab entry (invisible to the scheduler's own
bookkeeping), the natural home is the *same* registration crt already has
in `schedule/crt.conf` — see that file's own comments for the existing
Tier 2 paced-participant wiring. A `DEPLOY_FRESH_CMD`-style probe hook
already exists in `bin/morning-report.sh` for a conceptually similar
"is something out there stale relative to here" check (used today for
deploy-pending detection) — the sync pull is a similar shape (pull
freshness from an external host) but isn't quite the same mechanism
(that hook reports staleness, it doesn't run a real rsync side effect).
Simplest honest option: a small addition to `schedule/crt.conf` itself
that runs `crt-sync-vm-reports.sh` as a pre-step before crt's existing
paced Tier 2 run, so a sync happens on the same cadence crt already gets
scheduled time on, without inventing a new registration mechanism. Not
applied this session — this is exactly the kind of shared-scheduler-state
change that should be confirmed before running, see the open item above.

## Manual install steps (once there's VM access again)
```
# on crt-vm, after `git pull`:
sed "s/@USER@/$USER/g; s#@PROJECT_DIR@#$HOME/crt#g" \
  systemd/crt-vm-hardware-check.service | sudo tee \
  /etc/systemd/system/crt-vm-hardware-check.service
sudo cp systemd/crt-vm-hardware-check.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now crt-vm-hardware-check.timer
```

## Status
Job spec, service/timer units, and the sync script are written and
syntax-checked, nothing installed or run (no VM access this session). The
report-merging question above is the one real open design decision
blocking this from being fully wired end-to-end.
