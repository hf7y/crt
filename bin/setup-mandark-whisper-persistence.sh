#!/bin/bash
# Run this yourself (needs sudo). Opens the LAN port and installs a systemd
# user-independent service so mandark-whisper-server.py survives reboots
# and doesn't depend on this shell staying open.
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
ExecStart=/home/zach/.venvs/crt-whisper-server/bin/python /home/zach/Documents/Projects/crt/bin/mandark-whisper-server.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now crt-whisper-server.service
sudo systemctl status crt-whisper-server.service --no-pager
