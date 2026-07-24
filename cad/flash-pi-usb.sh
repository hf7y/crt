#!/bin/bash
set -euo pipefail

DEV=/dev/sda
IMG_URL="https://downloads.raspberrypi.com/raspios_lite_arm64_latest"
IMG=/home/zach/Documents/Projects/crt/cad/raspios_lite_arm64.img.xz
HOSTNAME=crt-pi
USER=vkv

if [ "$(id -u)" -ne 0 ]; then
  echo "run with sudo" >&2
  exit 1
fi

echo "Target: $DEV"
lsblk "$DEV"
read -p "This will ERASE $DEV. Type YES to continue: " CONFIRM
[ "$CONFIRM" = "YES" ] || { echo "aborted"; exit 1; }

umount "${DEV}"?* 2>/dev/null || true

if [ ! -f "$IMG" ]; then
  echo "Downloading Raspberry Pi OS Lite (64-bit)..."
  curl -L "$IMG_URL" -o "$IMG"
fi

echo "Flashing with rpi-imager..."
rpi-imager --cli --disable-verify "$IMG" "$DEV"

echo "Waiting for kernel to re-read partition table..."
BOOT_PART="${DEV}1"
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

echo "Setting hostname to $HOSTNAME..."
echo "$HOSTNAME" > /mnt/pi-boot/hostname 2>/dev/null || true

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
echo "Pi 3B USB-mass-storage boot needs boot ROM support (bootloader from ~2020+) --"
echo "if it doesn't boot from USB, boot once from an SD card with program_usb_boot_mode=1"
echo "in config.txt first, then this USB drive should boot directly on reboots after."
