# zaxon -- the relay that carries a question to a human, as a container.
# WHAT IS AND IS NOT BAKED IN. The image carries the RUNTIME only: python 3.11
# (matching the app's venv), node 22 (the Baileys bridge), and a zaxon user at
# uid 1000 so bind-mounted data keeps its ownership. ~/.hermes itself -- 558M,
# and holder of the WhatsApp session, kanban db and memories -- is a BIND MOUNT,
# not a COPY: baking it in would make the image secret-bearing and would fork
# the state the moment anyone rebuilt. The image is runtime; the mount is identity.
#
# The venv's shebangs are absolute, so the mount point MUST be /home/zaxon/.hermes.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates gnupg ffmpeg procps \
 && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg -o /usr/share/keyrings/githubcli-archive-keyring.gpg \
 && chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
 && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" > /etc/apt/sources.list.d/github-cli.list \
 && apt-get update && apt-get install -y --no-install-recommends gh \
 && rm -rf /var/lib/apt/lists/*
# gh, for the watcher's zaxon_relay_filer.py (crt#154) to file a pointer
# issue when an inbox note gets tagged. Reads auth from GH_TOKEN, set on the
# watcher service in compose.yaml.

# The relay's venv is python 3.14 and unusable here, so its one dependency (mcp)
# is installed into the image; the rest is stdlib, delivery uses hermes's venv.
RUN pip install --no-cache-dir mcp

RUN useradd -m -u 1000 -s /bin/bash zaxon

# Pre-create the XDG dirs OWNED BY zaxon: docker creates a bind mount's parents
# as root, so mounting ./uv made ~/.local root-owned and the gateway could not
# write its session lock (2026-08-14). Created first, the mount replaces only its leaf.
RUN mkdir -p /home/zaxon/.local/share /home/zaxon/.local/state /home/zaxon/.cache \
 && chown -R zaxon:zaxon /home/zaxon/.local /home/zaxon/.cache

# THE RELAY'S SOURCE IS IMAGE, NOT MOUNT. It lived in the mount until 2026-08-19,
# so .deploykeep rightly refused to overwrite it and no deploy could reproduce
# it. Its db and offset resolve through Path.home() and stay put; the code moved.
COPY relay/ /opt/zaxon-relay/

USER zaxon
WORKDIR /home/zaxon/.hermes
ENV HOME=/home/zaxon \
    USER=zaxon \
    LOGNAME=zaxon \
    HERMES_HOME=/home/zaxon/.hermes \
    VIRTUAL_ENV=/home/zaxon/.hermes/hermes-agent/.venv \
    PATH=/home/zaxon/.hermes/hermes-agent/.venv/bin:/home/zaxon/.local/bin:/usr/local/bin:/usr/bin:/bin

# One process per container. The bridge is a second SERVICE, not a second
# process here, so `restart: always` restarts whichever one actually died.
CMD ["python", "-m", "hermes_cli.main", "gateway", "run"]
