#!/bin/bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "run with sudo" >&2
  exit 1
fi

DEV=/dev/sda
BOOT_PART="${DEV}1"
USER=admin

for i in $(seq 1 15); do
  partprobe "$DEV" 2>/dev/null || true
  [ -b "$BOOT_PART" ] && break
  sleep 1
done
if [ ! -b "$BOOT_PART" ]; then
  echo "Partition $BOOT_PART never showed up. Unplug/replug the drive and re-run this script." >&2
  exit 1
fi

mkdir -p /mnt/pi-boot
umount /mnt/pi-boot 2>/dev/null || true
mount "$BOOT_PART" /mnt/pi-boot

echo "Enabling SSH..."
touch /mnt/pi-boot/ssh

echo "Setting hostname to crt-pi..."
echo "crt-pi" > /mnt/pi-boot/hostname 2>/dev/null || true

PW=""
while [ -z "$PW" ]; do
  echo -n "Enter password for user '$USER' (cannot be blank): "
  read -rs PW
  echo
done
HASH=$(echo "$PW" | openssl passwd -6 -stdin)
echo "$USER:$HASH" > /mnt/pi-boot/userconf.txt

df -h /mnt/pi-boot
ls -la /mnt/pi-boot/
umount /mnt/pi-boot

echo "DONE. Insert into Pi 3B and power on."
