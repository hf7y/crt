# zaxon — crt's WhatsApp channel

**crt owns zaxon as of 2026-08-14 (Zach's call.)** `SECRETARY.md` already says
what this project is: *"crt as a phone secretary, not a raw Claude Code
terminal."* zaxon is that same secretary reached over WhatsApp instead of over
the handset. One project, several front ends — handset in / CRT out, WhatsApp
in / WhatsApp out — and one STT service behind them, instead of two copies of
whisper maintained by nobody in particular.

It was previously nobody's: it ran in a WSL distro called `hermes` on dexter
that no ecosystem document mentioned, and was dead for ten days before a
groc-mangr dispatch run happened to try it.

## What it is

An MCP server over streamable-http exposing two tools — `ask_zach(question,
from_agent)` returns a ticket immediately, `check_zach_reply(ticket_id)` polls
for the human's answer. The contract lives at `~/.hermes/ZAXON_MCP_USAGE.md`
inside the service; `realisateur/ZAXON.md` is the estate-facing map of how to
reach it.

Two processes, both from this image:

- **gateway** — `hermes-agent`, a Python venv service (`hermes_cli.main gateway
  run`). Also carries Slack and Signal channel definitions, unused today.
- **bridge** — Baileys (`@whiskeysockets/baileys`), Node + express on :3000,
  the actual WhatsApp link.

## The one rule that matters

`data/whatsapp/session` is a **linked-device** session. The phone does not need
to stay powered on — it pairs the link and refreshes it roughly every two weeks.
But **exactly one process may hold that session**: two, and WhatsApp logs the
link out, and recovering costs a QR scan on Zach's phone.

So: never run this container while the `hermes` distro is up.
`realisateur/bin/dexter-service-deploy.sh` refuses to, and its test suite proves
the refusal pushes nothing and starts nothing.

## Deploying

The container channel is realisateur's road; the freight is ours.

```
realisateur/bin/dexter-service-deploy.sh zaxon          # push + compose up -d
realisateur/bin/dexter-liveness.sh                      # verify from anywhere
```

`data/` is service state — the WhatsApp session, the kanban db, the memories —
and is never overwritten from a repo. The image carries runtime only; see the
Dockerfile's header for why baking `~/.hermes` in would be wrong.

## Open

- `whisper-server` (STT) still runs inside the `hermes` distro. It is the same
  job `potato` already does locally for the handset. Moving it into a container
  beside this one is act 4 of realisateur#250; whether the Pi keeps doing its
  own STT is a real question, not a default.
- There is **no auth** on the MCP port. Anyone who can reach it can send Zach a
  WhatsApp message as any `from_agent` they name.
