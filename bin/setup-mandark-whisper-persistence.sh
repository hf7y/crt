#!/bin/bash
# Run this yourself (needs sudo). Opens the LAN port and installs a systemd
# user-independent service so the whisper server survives reboots and doesn't
# depend on this shell staying open.
#
# 2026-07-29: ExecStart now names bin/crt-whisper-server.py (the one
# host-agnostic implementation) instead of bin/mandark-whisper-server.py, which
# is now a compat shim onto it. This changes what a FRESH install writes; the
# unit ALREADY running on mandark still names the old path and still works via
# that shim. To move the live unit over, follow the retire-the-shim steps in
# bin/mandark-whisper-server.py's header -- it must be done ON mandark, because
# it needs a daemon-reload plus a /health check that nothing else can witness.
# See bin/setup-dexter-whisper-persistence.sh for the second host.
set -euo pipefail

sudo ufw allow 8991/tcp comment 'crt whisper server (LAN STT)'

sudo tee /etc/systemd/system/crt-whisper-server.service > /dev/null <<'EOF'
[Unit]
Description=crt console whisper transcription server (mandark)
After=network.target

[Service]
Type=simple
User=zach
WorkingDirectory=/home/zach/Documents/Projects/crt
Environment=CRT_WHISPER_TAG=mandark
ExecStart=/home/zach/.venvs/crt-whisper-server/bin/python /home/zach/Documents/Projects/crt/bin/crt-whisper-server.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now crt-whisper-server.service
sudo systemctl status crt-whisper-server.service --no-pager
