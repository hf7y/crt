# zaxon -- the relay that carries a question to a human, as a container.
#
# WHAT IS AND IS NOT BAKED IN. The image carries the RUNTIME only: python 3.11
# (matching the venv the app already has), node 22 (the Baileys bridge), and a
# zaxon user at uid 1000 so the bind-mounted data keeps its ownership. The app
# itself -- ~/.hermes, 558M including its own .venv and node_modules -- is a
# BIND MOUNT, not a COPY.
#
# That is deliberate and worth defending: ~/.hermes holds the WhatsApp
# linked-device session, the kanban db, and the memories. Baking it into an
# image would make the image secret-bearing and would fork the state the moment
# anyone rebuilt. The image is the runtime; the mount is the identity.
#
# The venv's shebangs are absolute (/home/zaxon/.hermes/hermes-agent/.venv/...),
# so the mount point MUST be /home/zaxon/.hermes. Same path in, same path out.
FROM python:3.11-slim

# node 22 to match what the hermes distro runs (v22.22.1, probed 2026-08-14);
# the Baileys bridge is ESM and version-sensitive.
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates gnupg ffmpeg procps \
 && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && rm -rf /var/lib/apt/lists/*

# uid 1000 matches zaxon inside the hermes distro (probed: uid=1000(zaxon)),
# so the bind-mounted session files stay readable and stay owned by a
# non-root user.
RUN useradd -m -u 1000 -s /bin/bash zaxon

USER zaxon
WORKDIR /home/zaxon/.hermes
ENV HOME=/home/zaxon \
    USER=zaxon \
    LOGNAME=zaxon \
    HERMES_HOME=/home/zaxon/.hermes \
    VIRTUAL_ENV=/home/zaxon/.hermes/hermes-agent/.venv \
    PATH=/home/zaxon/.hermes/hermes-agent/.venv/bin:/home/zaxon/.local/bin:/usr/local/bin:/usr/bin:/bin

# One process per container: this one is the gateway. The Baileys bridge is a
# second service in compose.yaml, not a second process here -- so that when one
# dies, `restart: always` restarts the one that died.
CMD ["python", "-m", "hermes_cli.main", "gateway", "run"]
