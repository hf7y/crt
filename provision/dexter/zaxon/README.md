# zaxon — crt's WhatsApp channel

**crt owns zaxon as of 2026-08-14 (Zach's call.)** An MCP server over
streamable-http exposing `ask_zach`, `revise_zach_question` and
`check_zach_reply`; loopback and tailnet only (#52). See `compose.yaml` for the
rest. One question per ticket, enforced at the send (crt#190) -- see the
`instructions=` string in `relay/zaxon_relay_server.py`.

Deploys are automatic — `zaxon-autoupdate.timer` pulls hourly and verifies the
relay answers. By hand: `sudo docker compose pull && sudo docker compose up -d`
(`sudo` because `zach` is not in the `docker` group).

`data/` is service state, never overwritten from a repo; the relay's SOURCE ships in the image.

## The status page

`hf7y.com/zaxon` — `zaxon-watch.sh --apply` hourly, `--install` writes the timer,
`--check` publishes nothing. What used to be written down here as rules a reader
had to remember is enforced by `tests/test_zaxon_watch_guards.sh` and reported
by the page itself: the one-holder rule for `data/whatsapp/session` and
`data/auth.json` (crt#193, crt#195), the never-bind-`0.0.0.0` rule, where the
STT command lives, and why a relay that merely answers is never `OK`.

## Open

- `hermes` is still registered and can still seize the session (page reports it hourly); before `wsl --unregister hermes`, its verified `.vhdx`/`ggml-base.en.bin` export is at `/mnt/d/gardien-backups/hermes-wsl-export/` on dexter.
- **Opt-in shared-secret auth landed (crt#194)** — `relay/zaxon_relay_server.py`
  refuses any request missing the right `X-Zaxon-Shared-Secret` header once
  `ZAXON_SHARED_SECRET` is set, but ships unconfigured (a no-op, same as
  before) until dexter's own `provision/dexter/zaxon/.env` sets it. Still
  unauthenticated on the tailnet until that step happens.
- Stop the old stack before starting a new one against this same `data/`: two stacks holding one
  Nous refresh token revoked the session for 8 days (crt#193, 2026-08-30's migration overlap).
