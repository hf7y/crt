# whisper — crt's STT service

whisper.cpp `v1.9.3`, answering `POST /inference` on `:8090`, at `/srv/whisper`
on dexter. Callers use the tailnet address `http://100.107.253.56:8090`: potato's
console (`CRT_WHISPER_SERVER`) and zaxon's `relay/bin/whisper_stt.sh`
(`WHISPER_URL`). The `Dockerfile` header says why it is a build, not a lift.

Its own compose project since crt#319: in zaxon's network namespace, every
gateway recreate took the room's STT down with it. The WhatsApp bridge is why
zaxon's relay and watcher stay in that namespace; whisper has no such tie.

Not on `zaxon-autoupdate.timer`, which watches `/srv/zaxon` only. After an image
change, by hand:

```
cd /srv/whisper && sudo docker compose pull && sudo docker compose up -d
docker exec zaxon-gateway /opt/zaxon-relay/bin/stt-selftest.sh   # a real transcript, not a port check
```
