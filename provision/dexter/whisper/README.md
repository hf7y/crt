# whisper — the STT service zaxon calls

whisper.cpp `v1.9.3`, answering `POST /inference` on `:8090`, the endpoint
`../zaxon/relay/bin/whisper_stt.sh` has always called. The `Dockerfile` header
carries the rest: why the binary is rebuilt rather than lifted out of the dead
`hermes` distro, where the model's checksum comes from, and why the service block
lives in `../zaxon/compose.yaml`.

```
cd /srv/zaxon && docker compose pull && docker compose up -d
# then confirm with a real transcript, not just a port check
```
