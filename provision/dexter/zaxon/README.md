# zaxon — crt's WhatsApp channel

**crt owns zaxon as of 2026-08-14 (Zach's call.)** It was previously nobody's — it
ran in a WSL distro (`hermes`) no document named, dead ten days before a groc-mangr
run happened to try it. An MCP server over streamable-http exposing `ask_zach` and
`check_zach_reply`; loopback and tailnet only (#52). See `compose.yaml` for the rest.

## The one rule that matters

`data/whatsapp/session` is a **linked-device** session and **exactly one process
may hold it**; two, and WhatsApp logs the link out, costing a QR scan. `hermes`
boots `systemd` with `hermes-gateway.service` enabled, so *starting that distro at
all* takes it — mount its `.vhdx` offline instead. `dexter-service-deploy.sh` used
to refuse for you; realisateur#511 deleted it, so the rule is yours now.

```
cd /srv/zaxon && docker compose pull && docker compose up -d
# then verify from anywhere: confirm a real transcript, not just a port
```

`data/` is service state, never overwritten from a repo; the relay's SOURCE ships in the image.

## The STT command

`HERMES_LOCAL_STT_COMMAND` lives in `compose.yaml`, pointing at
`/opt/zaxon-relay/bin/whisper_stt.sh` which the Dockerfile `COPY`s out of `relay/`.
It used to sit in `data/.env`, inside the bind mount `.deploykeep` shields from
every deploy — so the repo's copy never ran. `.env` loads with `override=True` and
**beats** compose, so the old line stays commented out there.

## Open

- `hermes` is still registered and Stopped. Before `wsl --unregister hermes`: its
  verified `.vhdx` export and extracted `ggml-base.en.bin` are at
  `/mnt/d/gardien-backups/hermes-wsl-export/` on dexter.
- Still **no auth** on the MCP port, only a bind — today, the tailnet.
