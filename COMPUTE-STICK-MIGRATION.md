# Compute stick migration (Intel Compute Stick STK1AW32SC)

Side task, unrelated to the crt voice console's STT mission — flashing a USB
stick to install Debian on an Intel Compute Stick ahead of migrating project
files to a single system. Documented here for reference and so a future
agent picking this up mid-stream has the full story.

## Hardware

- **Device**: Intel Compute Stick **STK1AW32SC** — Atom Z3735F (Bay Trail),
  1GB RAM, 32GB eMMC, 2 USB ports, microSD slot (not bootable — secondary
  storage bus only).
- **Critical quirk**: ships with **32-bit UEFI firmware** despite a 64-bit
  CPU. A standard 64-bit ISO's `bootx64.efi` cannot be executed by this
  firmware — confirmed live via the internal UEFI Shell, which itself only
  runs `ia32` images (proof the firmware is genuinely 32-bit, not just a
  BIOS setting).
- **Also broken**: no usable video output for the Debian installer on this
  hardware. GRUB reports "no suitable video mode, booting blind" and the
  installer kernel never produces a picture, with or without `nomodeset`.
  Likely cause: PowerVR SGX544 graphics unsupported by stock kernel +
  flaky EFI framebuffer handoff across the 32-bit-firmware/64-bit-kernel
  boundary. Confirmed alive via Caps Lock toggling (keyboard/kernel
  responsive) with zero video regardless of cmdline flags tried
  (`nomodeset`, explicit `console=`, `fb=false`). **Working assumption:
  this install has to happen fully blind, via preseed.**
- USB stick used for all of this: `/dev/sda` on `mandark` (7.5GB, labeled
  WESDATA originally — user confirmed already backed up and safe to wipe).

## Distro choice: Debian, not Ubuntu

Ubuntu Server ISOs (24.04.x) dropped 32-bit EFI support — only ship
`bootx64.efi`. **Debian's netinst ISO turned out to also be 64-bit-only**
in the same way (confirmed by inspecting `EFI/boot/` inside the ISO — only
`bootx64.efi` + `grubx64.efi`, no `bootia32.efi`). The "Debian ships both"
assumption made early in this session was wrong and cost a round-trip.
Debian was still the right call for the OS itself (glibc/apt compatibility,
lighter base than Ubuntu Server) — the 32-bit boot problem had to be solved
separately (see below), and would have needed solving for any modern distro
on this firmware.

Also note: Debian dropped official **i386** netinst ISOs too (404 on
`cdimage.debian.org/debian-cd/current/i386/` for current release) — so
"just grab bootia32.efi from the i386 ISO" doesn't work anymore either.
Solution was to build one locally instead (see below).

## Getting a 32-bit UEFI bootloader

Package `grub-efi-ia32-bin` (from Ubuntu/Debian archives, available via
`apt` even on the amd64 `mandark` host) provides the modules needed to
build a standalone ia32 EFI binary with `grub-mkstandalone`.

**First attempt failed for a subtle reason worth remembering**: a
standalone GRUB that just `chainloader`s `BOOTX64.EFI` hits the *exact
same* "image type x64 not supported" error, because chainloading still
asks the firmware to execute an x64 PE binary directly. The fix that
actually works: have the **32-bit GRUB load the Linux kernel itself**
(`linux` / `initrd` commands), since GRUB's own kernel loader does the
long-mode switch internally and never asks the firmware to execute a
64-bit PE image. This is the real mechanism behind "32-bit UEFI can boot a
64-bit OS" — it's GRUB doing a mode switch, not firmware mixed-mode
support (which this firmware doesn't have).

Build command (see `cad/flash-bootia32.sh` for the working version):

```
grub-mkstandalone -O i386-efi --compress=xz \
  -o BOOTIA32.EFI \
  --modules="part_gpt part_msdos fat iso9660 linux normal search" \
  "boot/grub/grub.cfg=/dev/stdin" <<'GRUBCFG'
insmod part_gpt
insmod part_msdos
insmod fat
insmod iso9660
insmod linux
search --no-floppy --set=root --file /install.amd/vmlinuz
linux /install.amd/vmlinuz ---
initrd /install.amd/initrd.gz
boot
GRUBCFG
```

Gotchas hit along the way:
- Building to `/tmp` failed with `Permission denied` even as root on this
  host — build to a project path instead (see script).
- The stick's ESP (`sda2`) is only **3.6MB** — barely fits one GRUB image.
  Had to drop `all_video` module and add `--compress=xz`, and delete the
  now-unneeded `grubx64.efi` to make room.
- `mount` can fail with "already mounted" if a previous manual check left
  `/mnt/stick` mounted — scripts now `umount ... || true` defensively first.

## Disk layout on the stick after `dd`

The Debian netinst ISO is a hybrid isohybrid image. `dd`-ing it to `/dev/sda`
produces an odd-looking but *normal* layout:

```
/dev/sda1   755M  iso9660         (whole-image placeholder, "Empty" type in fdisk)
/dev/sda2   3.6M  vfat, type ef   (the real ESP — EFI/BOOT/*.efi lives here)
```

`sda1` and `sda2` **intentionally overlap** in sector ranges — this is
normal isohybrid structure, not corruption. `gdisk` gets confused and
prompts "MBR or GPT?" because of leftover GPT structures — **just answer
`q` to quit without writing, never pick 1/2/3** unless you mean to
convert the table. Use `sfdisk`/`fdisk` (which correctly report
`Disklabel type: dos`) instead of `parted` (reported "Partition Table:
unknown" on this image) or `gdisk`.

A third partition, `sda3`, was added afterward in the ~6.8GB of unused
space after `sda1` ends (sector 1546240 to end of disk) to hold installer
kernels/initrds without needing to remaster the whole ISO:

```
sudo sfdisk --append --no-reread /dev/sda   # start=1546240, type=c (W95 FAT32 LBA)
sudo mkfs.vfat -F 32 -n INSTALLDATA /dev/sda3
```

(`partprobe` after `sfdisk` appears to be unreliable/silent-failure-prone
on this host — the partition device node still showed up fine via
udev/kernel even when the script seemed to die after `sfdisk`. If a script
exits silently right after `sfdisk` with no `mkfs`/`DONE` output, just run
the format-and-copy steps as a separate follow-up script — don't assume
`sfdisk` itself failed.)

## Booting from the ia32 UEFI Shell (manual recovery path)

BIOS boot menu (F10) does **not** list the USB stick as a boot option on
this firmware even with USB Boot enabled — a known quirk, not a config
error. Recovery path when this happens: boot into the **Internal UEFI
Shell** (a BIOS boot-menu option) and drive it manually:

```
map -r                      # list filesystem mappings, look for the small FAT one
fs3:                        # (or whichever fsN: matches — varies by boot)
cd EFI\BOOT
BOOTIA32.EFI                # runs our standalone grub, which searches+boots the kernel
```

Device naming inside GRUB itself does **not** match the shell's `fsN:`
numbering — GRUB uses `(hd0)`, `(hd1)`, etc., and On this board `hd0` maps
to the **USB stick** while `hd1` turned out to be the **internal Windows
disk** (identified by finding `bcd`/`System Volume Information` when
listing `(hd1,gpt1)/`). The ISO9660 data partition on the stick shows up as
the raw whole-disk `(hd0)` itself, **not** as a numbered `(hd0,msdosN)`
partition — El Torito hybrid images often expose the ISO filesystem this
way. The writable `sda3` partition we added shows up as `(hd0,msdos3)`.

## Preseeding the install (fully unattended, since there's no video)

Since the installer can never be seen, the plan is to make it fully
unattended via Debian preseed, embedded directly into a modified initrd
(the standard "initrd preseeding" technique — append a tiny uncompressed
cpio archive containing `preseed.cfg` to the end of the existing
compressed `initrd.gz`; the kernel's initramfs unpacker handles
concatenated archives, and a later archive's files win over earlier ones
with the same path):

```
(cat original-initrd.gz; echo preseed.cfg | cpio -H newc -o) > initrd-preseeded.gz
```

Kernel cmdline to actually load and use it:

```
auto=true priority=critical preseed/file=/preseed.cfg
```

### Diagnostic-only preseed (safe, no disk writes)

Built first to nail down the *actual* internal eMMC device name without
risking a blind wipe of the wrong disk. Its `preseed/early_command` dumps
`/proc/partitions`, `/dev/disk/by-id`, and `lsblk` output to
`DISKINFO.TXT` on the stick's own ESP (`/dev/sda2`, mounted from within
the installer environment — same device numbering as the host since it's
the same kernel/udev), then calls `poweroff -f` **before partitioning ever
starts**. File: `preseed-diag.cfg` → baked into `initrd-diag.gz`.

### Candidate install preseeds (destructive — full wipe)

Two variants built speculatively for the two most likely internal device
names on this Bay Trail chipset, so no drive-pulling is needed between
attempts — just boot a different initrd from `sda3`:

- `preseed-mmcblk0.cfg` → `initrd-mmcblk0.gz` (targets `/dev/mmcblk0`)
- `preseed-mmcblk1.cfg` → `initrd-mmcblk1.gz` (targets `/dev/mmcblk1`)

Both: full-disk wipe (`partman-auto` atomic recipe), offline (network
disabled entirely — this stick's WiFi chip almost certainly lacks
firmware in the stock installer, and there's no wired ethernet), hostname
`crt-console`, user `vkv` with sudo (no separate root account — matches
`mandark`'s setup), `openssh-server` included for later remote access.
**Password is `summer08`, a placeholder the user chose — weak, meant to be
changed immediately after first login, not meant to persist.** A
`late_command` writes `INSTALL-OK.TXT` to the stick's ESP on success,
mirroring the diagnostic's approach, so success/failure can be confirmed
without needing to see a screen.

**Important**: these wipe the *entire* target disk. User explicitly chose
full wipe over a shrink-Windows dual-boot after being warned that blind
NTFS resizing (no screen to catch errors) is meaningfully riskier than a
clean wipe, and they're fine reinstalling Windows separately later if
ever needed.

## Scripts (in `cad/`, all require `sudo`, none can be run non-interactively
by an agent — this host's `sudo` has no cached credentials and no TTY for
password entry, so a human always has to run them)

- `flash-bootia32.sh` — builds and installs the ia32 GRUB chainloader/kernel-
  loader onto the stick's ESP.
- `add-installdata-partition.sh` — adds `sda3` in the stick's free space
  (the `mkfs`/copy steps in this one didn't run in practice — see below).
- `format-and-copy-installdata.sh` — formats `sda3` and copies
  `vmlinuz` + `initrd-diag.gz` onto it. Needed as a separate follow-up
  because `add-installdata-partition.sh`'s script died silently right
  after the `sfdisk` step in practice (never confirmed why — `partprobe`
  is the suspect but the partition device came up fine regardless).
- `copy-candidate-preseeds.sh` — copies the two `initrd-mmcblk*.gz`
  candidates onto `sda3` alongside the diagnostic files.

## Status as of this writing / next steps for whoever picks this up

1. Stick is fully prepped: ia32 bootloader on `sda2`, four boot payloads
   on `sda3` (`vmlinuz` shared + `initrd-diag.gz` / `initrd-mmcblk0.gz` /
   `initrd-mmcblk1.gz`).
2. **Not yet done**: user was about to run the diagnostic boot. Waiting
   on `DISKINFO.TXT` to come back (stick gets pulled, mounted on
   `mandark`, file read from `sda2`) to confirm the real internal disk
   device name before running either candidate install for real.
3. Once confirmed, boot the matching `initrd-mmcblkN.gz` — full cmdline
   pattern:
   ```
   linux (hd0,msdos3)/vmlinuz nomodeset console=tty1 auto=true priority=critical preseed/file=/preseed.cfg ---
   initrd (hd0,msdos3)/initrd-mmcblkN.gz
   boot
   ```
4. If the real device name doesn't match either candidate, a new preseed
   needs to be built (same template, `preseed-template.cfg` in the
   session scratchpad — **not committed to the repo, only lives in
   `/tmp/claude-*/scratchpad`, regenerate from this doc's contents if
   that's gone**) and a new initrd baked, following the same
   `cat + cpio` recipe above.
5. After a successful install: pull the USB stick, board should boot
   straight into Debian from internal storage — no more manual boot
   selection needed. If the ESP's `INSTALL-OK.TXT` isn't there and the
   board also doesn't boot into anything afterward, that's a sign the
   preseed hit an unhandled debconf prompt and hung blind — needs another
   diagnostic-style iteration to find out where.
