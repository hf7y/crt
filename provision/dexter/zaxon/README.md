# zaxon — crt's WhatsApp channel

**crt owns zaxon as of 2026-08-14 (Zach's call.)** `SECRETARY.md` says what this
project is — *"crt as a phone secretary, not a raw Claude Code terminal"* — and
zaxon is that secretary over WhatsApp instead of the handset. Several front ends,
one STT service behind them, rather than two copies of whisper owned by nobody.

It was previously nobody's: it ran in a WSL distro (`hermes`) no document
mentioned, and was dead ten days before a groc-mangr run happened to try it.

## What it is

An MCP server over streamable-http exposing two tools — `ask_zach(question,
from_agent)` returns a ticket immediately, `check_zach_reply(ticket_id)` polls
for the human's answer. `relay/zaxon_relay_server.py` carries the contract in
its own docstring; `compose.yaml` names the services and says why each is
separate. Reachable on loopback and the tailnet only, never the LAN (#52).

## The one rule that matters

`data/whatsapp/session` is a **linked-device** session — the phone need not stay
powered on; it refreshes the link roughly every two weeks. But **exactly one
process may hold it**: two, and WhatsApp logs the link out, costing a QR scan.

So: never run this container while the `hermes` distro is up.
`realisateur/bin/dexter-service-deploy.sh` refuses to, and its suite proves the
refusal pushes nothing and starts nothing.

## Deploying

The container channel is realisateur's road; the freight is ours.

```
realisateur/bin/dexter-service-deploy.sh zaxon          # push + compose up -d
realisateur/bin/dexter-liveness.sh                      # verify from anywhere
```

`data/` is service state — WhatsApp session, kanban db, memories — never
overwritten from a repo. The relay's SOURCE is in the image (`relay/`); only its
db and offset stay in the mount.

## Open

- `whisper-server` (STT) is **DEAD**, not merely unmigrated: a unit inside the
  Stopped `hermes` distro, so nothing serves :8090 and voice notes fail with
  exit 7. Act 4 of realisateur#250; lift the model out before act 3 unregisters.
- Still **no auth** on the MCP port, only a bind: whoever reaches it can message
  Zach as any `from_agent` — today, the tailnet.
