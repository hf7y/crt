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

mkdir -p /mnt/pi-root
umount /mnt/pi-root 2>/dev/null || true
mount "$ROOT_PART" /mnt/pi-root

sed -i 's/^XKBLAYOUT=.*/XKBLAYOUT="us"/' /mnt/pi-root/etc/default/keyboard
sed -i 's/^XKBMODEL=.*/XKBMODEL="pc105"/' /mnt/pi-root/etc/default/keyboard
grep XKB /mnt/pi-root/etc/default/keyboard

umount /mnt/pi-root
echo "DONE. Re-insert drive into the Pi and power on -- console will be US layout."
