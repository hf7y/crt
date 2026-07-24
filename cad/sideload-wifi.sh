#!/bin/bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "run with sudo" >&2
  exit 1
fi

DEV=/dev/sda
ROOT_PART="${DEV}2"

for i in $(seq 1 15); do
  partprobe "$DEV" 2>/dev/null || true
  [ -b "$ROOT_PART" ] && break
  sleep 1
done
if [ ! -b "$ROOT_PART" ]; then
  echo "Partition $ROOT_PART never showed up. Unplug/replug the drive and re-run this script." >&2
  exit 1
fi

echo -n "Wifi SSID: "
read -r SSID
echo -n "Wifi password: "
read -rs PSK
echo

mkdir -p /mnt/pi-root
umount /mnt/pi-root 2>/dev/null || true
mount "$ROOT_PART" /mnt/pi-root

CONN_DIR=/mnt/pi-root/etc/NetworkManager/system-connections
mkdir -p "$CONN_DIR"

cat > "$CONN_DIR/preconfigured.nmconnection" <<EOF
[connection]
id=preconfigured
uuid=$(cat /proc/sys/kernel/random/uuid)
type=wifi

[wifi]
mode=infrastructure
ssid=$SSID

[wifi-security]
key-mgmt=wpa-psk
psk=$PSK

[ipv4]
method=auto

[ipv6]
method=auto
addr-gen-mode=default

[proto]
EOF

chmod 600 "$CONN_DIR/preconfigured.nmconnection"

ls -la "$CONN_DIR"
umount /mnt/pi-root

echo "DONE. Re-insert drive into the Pi and power on -- it should join wifi automatically."
