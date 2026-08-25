# zaxon — crt's WhatsApp channel

**crt owns zaxon as of 2026-08-14 (Zach's call.)** An MCP server over
streamable-http exposing `ask_zach` and `check_zach_reply`; loopback and tailnet
only (#52). See `compose.yaml` for the rest.

## The one rule that matters

`data/whatsapp/session` is a **linked-device** session and **exactly one process
may hold it**; two, and WhatsApp logs the link out, costing a QR scan. `hermes`
boots `systemd` with `hermes-gateway.service` enabled, so *starting that distro at
all* takes it — mount its `.vhdx` offline instead. `dexter-service-deploy.sh` used
to refuse for you; realisateur#511 deleted it, so the rule is yours now.

Deploys are automatic — `zaxon-autoupdate.timer` pulls hourly and verifies the
relay answers. By hand: `sudo docker compose pull && sudo docker compose up -d`
(`sudo` because `zach` is not in the `docker` group).

`data/` is service state, never overwritten from a repo; the relay's SOURCE ships in the image.

## The STT command

`HERMES_LOCAL_STT_COMMAND` lives in `compose.yaml`, pointing at
`/opt/zaxon-relay/bin/whisper_stt.sh` which the Dockerfile `COPY`s out of `relay/`.
It used to sit in `data/.env`, inside the bind mount `.deploykeep` shields from
every deploy — so the repo's copy never ran. `.env` loads with `override=True` and
**beats** compose, so the old line stays commented out there.

## The status page

`hf7y.com/zaxon` — `zaxon-watch.sh --apply` hourly, installed once with
`sudo ./zaxon-watch.sh --install`. `--check` prints the document and publishes
nothing. It never alerts through zaxon: a channel cannot page a human about
being unable to page a human, so the page IS the alert.

**A relay that merely answers is never `OK`.** On 2026-08-25 all four
containers were up and the port answered in 3 ms while 18 of 18 questions in
24 h expired unanswered — 16 of them `ausculte-cadence` repeating three DOWN
sensors. With one slot (crt#67) an ignored question holds the channel for its
full TTL, so that day spent 18 of 24 hours unable to deliver anything else.
`stale_slot_hours` is that number.

## Open

- `hermes` is still registered and Stopped. Before `wsl --unregister hermes`: its
  verified `.vhdx` export and extracted `ggml-base.en.bin` are at
  `/mnt/d/gardien-backups/hermes-wsl-export/` on dexter.
- Still **no auth** on the MCP port, only a bind — today, the tailnet.
