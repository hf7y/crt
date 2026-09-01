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
