#!/bin/bash
# Run this yourself (needs sudo). Installs two systemd services on
# mandark so the bin/crt-remote-claude-bridge.py server and its reverse
# tunnel into potato survive reboots, instead of the ad-hoc `nohup`
# processes this session started manually.
#   [rest: vault:crt/header-archaeology-20260817.md]
set -euo pipefail

echo "Stopping ad-hoc nohup processes (harmless if already gone)..."
kill 756846 2>/dev/null || true
kill 756877 2>/dev/null || true
sleep 1

sudo tee /etc/systemd/system/crt-remote-claude-bridge.service > /dev/null <<'EOF'
[Unit]
Description=crt console remote-Claude bridge server (mandark side, 127.0.0.1-only)
After=network.target

[Service]
Type=simple
User=zach
WorkingDirectory=/home/zach/Documents/Projects/crt
ExecStart=/usr/bin/python3 /home/zach/Documents/Projects/crt/bin/crt-remote-claude-bridge.py --port 8993 --session potato-claude
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/crt-potato-tunnel.service > /dev/null <<'EOF'
[Unit]
Description=crt console reverse tunnel to potato (mandark:8993 -> potato:8993)
After=network.target crt-remote-claude-bridge.service
Wants=crt-remote-claude-bridge.service

[Service]
Type=simple
User=zach
ExecStart=/usr/bin/ssh -N -R 8993:localhost:8993 -o ServerAliveInterval=15 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes potato
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now crt-remote-claude-bridge.service
sudo systemctl enable --now crt-potato-tunnel.service

echo "--- bridge status ---"
sudo systemctl status crt-remote-claude-bridge.service --no-pager
echo "--- tunnel status ---"
sudo systemctl status crt-potato-tunnel.service --no-pager
