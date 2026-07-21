#!/usr/bin/env bash
# One-time setup on the Debian/Ubuntu VM. Installs deps, builds whisper.cpp,
# downloads a model, wires autologin on tty1, and makes tty1 boot straight
# into Claude Code + the voice-to-text feeder.
#
# Run as the user who will use the console (not root); it will sudo where needed.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_USER="$(whoami)"

### ------------------------------------------------------------------------
### CONFIG -- two equally-valid ways to fill these in:
###   1. Edit the values below directly (e.g. CRT_WIFI_SSID="MyNetwork"),
###      then just run ./install.sh with no env vars.
###   2. Leave a line as-is (its ${VAR:-} falls back to blank) and either
###      pass the env var on the command line (CRT_WIFI_SSID=... ./install.sh)
###      or answer the interactive prompt this script shows for it later --
###      prompts only fire when the value is still blank AND stdin is a
###      real terminal (`[ -t 0 ]`), so a non-interactive run (piped, cron,
###      another script) never hangs waiting on input.
### Secrets (WiFi password, Gemini key, Claude credentials) are never
### echoed back and never committed -- hand-edit this file locally if you
### use option 1 for those, don't check the edited copy into git.
### ------------------------------------------------------------------------
CRT_HOSTNAME="${CRT_HOSTNAME:-crt-console}"
CRT_WIFI_SSID="${CRT_WIFI_SSID:-}"
CRT_WIFI_PSK="${CRT_WIFI_PSK:-}"
CRT_WIFI_IFACE="${CRT_WIFI_IFACE:-wlan0}"
CRT_GEMINI_API_KEY="${CRT_GEMINI_API_KEY:-}"
CRT_CLAUDE_CREDENTIALS_PATH="${CRT_CLAUDE_CREDENTIALS_PATH:-}"
### --- end CONFIG ---

echo "==> Hostname + mDNS (crt-stick reachable as \$CRT_HOSTNAME.local)"
# avahi-daemon answers "who is $CRT_HOSTNAME.local?" over multicast DNS --
# no router config, no static IP reservation, no central DNS server. Same
# mechanism that already makes dexter.local reachable. Only works for
# other devices on the SAME LAN segment (multicast doesn't cross routers/
# VLANs) -- crt-console.sh's boot-time IP flash (see that file) is the
# fallback when it doesn't apply.
sudo apt-get install -y avahi-daemon
CURRENT_HOSTNAME="$(hostname)"
if [ "$CURRENT_HOSTNAME" != "$CRT_HOSTNAME" ]; then
  sudo hostnamectl set-hostname "$CRT_HOSTNAME"
  echo "    hostname set: $CURRENT_HOSTNAME -> $CRT_HOSTNAME (reachable as $CRT_HOSTNAME.local)"
else
  echo "    already $CRT_HOSTNAME, skipping"
fi

echo "==> WiFi (optional -- set CRT_WIFI_SSID/CRT_WIFI_PSK/CRT_WIFI_IFACE)"
if [ -z "$CRT_WIFI_SSID" ] && [ -t 0 ]; then
  read -r -p "    WiFi SSID (or Enter to skip WiFi setup, e.g. already on ethernet): " CRT_WIFI_SSID
fi
if [ -n "$CRT_WIFI_SSID" ] && [ -z "$CRT_WIFI_PSK" ] && [ -t 0 ]; then
  read -r -s -p "    WiFi password for '$CRT_WIFI_SSID': " CRT_WIFI_PSK
  echo ""
fi
# Runs early (before apt-get update): on a compute-stick deployment with no
# ethernet, this may be the only path to network at all, including for the
# rest of this script. Two backends, whichever is actually present --
# NOT hardware-verified against a real stick's wifi adapter yet, same
# acceptance bar as everything else in this repo (see this file's own
# convention of flagging untested paths rather than claiming they work).
if [ -n "$CRT_WIFI_SSID" ]; then
  if command -v nmcli >/dev/null 2>&1; then
    sudo nmcli device wifi connect "$CRT_WIFI_SSID" password "$CRT_WIFI_PSK" ifname "$CRT_WIFI_IFACE" \
      && echo "    connected via NetworkManager ($CRT_WIFI_IFACE)" \
      || echo "    nmcli connect failed -- check SSID/password and that $CRT_WIFI_IFACE exists"
  elif command -v wpa_passphrase >/dev/null 2>&1; then
    # Minimal Debian installs (no NetworkManager) ship ifupdown +
    # wpasupplicant instead. wpa_passphrase hashes the PSK into the config
    # file rather than storing it in plaintext -- but it also emits a
    # "#psk=..." COMMENT line with the raw passphrase by default; strip
    # that line, only the hash needs to persist to disk.
    WPA_CONF="/etc/wpa_supplicant/wpa_supplicant-${CRT_WIFI_IFACE}.conf"
    {
      echo "ctrl_interface=/run/wpa_supplicant"
      echo "update_config=1"
      wpa_passphrase "$CRT_WIFI_SSID" "$CRT_WIFI_PSK" | grep -v '^#psk='
    } | sudo tee "$WPA_CONF" >/dev/null
    sudo chmod 600 "$WPA_CONF"
    if ! grep -q "iface $CRT_WIFI_IFACE" /etc/network/interfaces 2>/dev/null; then
      printf 'auto %s\niface %s inet dhcp\n    wpa-conf %s\n' \
        "$CRT_WIFI_IFACE" "$CRT_WIFI_IFACE" "$WPA_CONF" \
        | sudo tee -a /etc/network/interfaces >/dev/null
    fi
    sudo systemctl restart networking 2>/dev/null || sudo ifup "$CRT_WIFI_IFACE" 2>/dev/null || true
    echo "    wrote $WPA_CONF + /etc/network/interfaces stanza for $CRT_WIFI_IFACE"
  else
    echo "    neither nmcli nor wpa_passphrase found -- install network-manager or"
    echo "    wpasupplicant first, or connect via ethernet and skip this for now."
  fi
else
  echo "    CRT_WIFI_SSID not set, skipping (assuming ethernet or already-connected wifi)"
fi

echo "==> Installing packages"
sudo apt-get update
sudo apt-get install -y build-essential cmake git tmux sox alsa-utils curl openscad evtest jq

echo "==> Installing Claude Code CLI"
if ! command -v claude >/dev/null 2>&1; then
  curl -fsSL https://claude.ai/install.sh | bash
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
  export PATH="$HOME/.local/bin:$PATH"
else
  echo "    claude already installed, skipping"
fi

echo "==> Claude Code credentials (optional -- set CRT_CLAUDE_CREDENTIALS_PATH, or paste)"
# claude's own OAuth login is interactive by default (visit a URL, paste a
# code back -- text-only, no browser needed on THIS machine, but still a
# one-time human step). Pre-seeding ~/.claude/.credentials.json skips that
# entirely on first boot -- the same mechanism svc-vaporwave's own
# nightly-batch jobs already use for fully unattended `claude -p` runs.
# Do the one-time login ONCE on any machine that already has a real
# ~/.claude/.credentials.json, then either point CRT_CLAUDE_CREDENTIALS_PATH
# at that file directly (preferred -- the content never has to transit a
# terminal at all), or paste its contents at the prompt below if copying
# the file over isn't convenient. Never paste it into a chat/prompt with an
# AI assistant, same handling as the Gemini key above -- this script's own
# interactive prompt (a real local terminal) is a different, fine, channel.
CRT_CLAUDE_CREDS_TMP=""
if [ -z "$CRT_CLAUDE_CREDENTIALS_PATH" ] && [ -t 0 ] && [ ! -f "$HOME/.claude/.credentials.json" ]; then
  echo "    Paste the full contents of .credentials.json below, then a line"
  echo "    containing just EOF -- or press Enter on an empty first line to"
  echo "    skip and log in interactively on first run instead."
  first_line=""
  IFS= read -r first_line || true
  if [ -n "$first_line" ]; then
    CRT_CLAUDE_CREDS_TMP="$(mktemp)"
    {
      printf '%s\n' "$first_line"
      while IFS= read -r paste_line; do
        [ "$paste_line" = "EOF" ] && break
        printf '%s\n' "$paste_line"
      done
    } > "$CRT_CLAUDE_CREDS_TMP"
    if jq empty "$CRT_CLAUDE_CREDS_TMP" 2>/dev/null; then
      CRT_CLAUDE_CREDENTIALS_PATH="$CRT_CLAUDE_CREDS_TMP"
    else
      echo "    Pasted content isn't valid JSON -- skipping, discarding the paste."
      rm -f "$CRT_CLAUDE_CREDS_TMP"
      CRT_CLAUDE_CREDS_TMP=""
    fi
  fi
fi
if [ -n "$CRT_CLAUDE_CREDENTIALS_PATH" ]; then
  if [ -f "$CRT_CLAUDE_CREDENTIALS_PATH" ]; then
    mkdir -p "$HOME/.claude"
    umask 077
    cp "$CRT_CLAUDE_CREDENTIALS_PATH" "$HOME/.claude/.credentials.json"
    chmod 600 "$HOME/.claude/.credentials.json"
    umask 022
    echo "    Installed to ~/.claude/.credentials.json -- no first-run login needed"
  else
    echo "    CRT_CLAUDE_CREDENTIALS_PATH=$CRT_CLAUDE_CREDENTIALS_PATH not found, skipping"
  fi
else
  echo "    Not set -- 'claude' will prompt for a one-time login on first run"
fi
# Shred the temp copy of a pasted credential either way (installed or not) --
# it's the plaintext OAuth token, don't leave it sitting in a tempdir.
if [ -n "$CRT_CLAUDE_CREDS_TMP" ] && [ -f "$CRT_CLAUDE_CREDS_TMP" ]; then
  shred -u "$CRT_CLAUDE_CREDS_TMP" 2>/dev/null || rm -f "$CRT_CLAUDE_CREDS_TMP"
fi

echo "==> Building whisper.cpp"
if [ ! -d "$HOME/whisper.cpp" ]; then
  git clone --depth 1 https://github.com/ggml-org/whisper.cpp "$HOME/whisper.cpp"
fi
cmake -S "$HOME/whisper.cpp" -B "$HOME/whisper.cpp/build" -DCMAKE_BUILD_TYPE=Release
cmake --build "$HOME/whisper.cpp/build" -j"$(nproc)" --config Release

WHISPER_MODEL_NAME="${CRT_WHISPER_MODEL_NAME:-base.en}"
echo "==> Downloading STT model ($WHISPER_MODEL_NAME)"
bash "$HOME/whisper.cpp/models/download-ggml-model.sh" "$WHISPER_MODEL_NAME"

echo "==> Granting audio device access"
# Without desktop/logind session ACLs, /dev/snd/* is only reachable via the
# 'audio' group. The tty1 console login gets a logind seat (ACL) for free, but
# SSH sessions and headless testing don't -- add the user to 'audio' so mic
# capture works regardless of how the console is reached.
sudo usermod -aG audio "$TARGET_USER"

echo "==> Installing shared-capture ALSA config"
# Defines the 'crtmic' dsnoop device so the STT loop and the live level meter can
# both read the microphone at once (raw ALSA hw capture is single-consumer).
# Harmless on hardware where the meter isn't used. Only install if the config
# references card 0's hardware; on a box where the mic is a different card,
# adjust systemd/asound.conf first (see CRT_ALSA_CARD / the 'hw:0,0' slave).
sudo cp "$PROJECT_DIR/systemd/asound.conf" /etc/asound.conf

echo "==> Configuring tty1 autologin"
sudo mkdir -p /etc/systemd/system/getty@tty1.service.d
sed "s/@USER@/$TARGET_USER/g" "$PROJECT_DIR/systemd/autologin.conf" \
  | sudo tee /etc/systemd/system/getty@tty1.service.d/autologin.conf >/dev/null
sudo systemctl daemon-reload
sudo systemctl restart getty@tty1

echo "==> Wiring console autostart"
if ! grep -q "crt autoboot" "$HOME/.bash_profile" 2>/dev/null; then
  {
    echo "export CRT_PROJECT_DIR=\"$PROJECT_DIR\""
    if [ "$WHISPER_MODEL_NAME" != "base.en" ]; then
      echo "export CRT_WHISPER_MODEL=\"\$HOME/whisper.cpp/models/ggml-${WHISPER_MODEL_NAME}.bin\""
    fi
    cat "$PROJECT_DIR/systemd/bash_profile.append"
  } >> "$HOME/.bash_profile"
else
  echo "    already wired, skipping"
fi

echo "==> Gemini API key (bin/crt-book-game.py's cheap-tier question source)"
if [ -z "${CRT_GEMINI_API_KEY:-}" ] && [ -t 0 ]; then
  # Interactive terminal, no env var pre-set -- prompt instead of requiring
  # the caller to know the CRT_GEMINI_API_KEY incantation. `read -s` hides
  # the paste (no echo), matching how the crt-vm password prompt is
  # handled elsewhere in this project. Skips cleanly (no prompt hang) when
  # install.sh is run non-interactively (piped, cron, another script),
  # since `-t 0` is false there.
  read -r -s -p "    Paste Gemini API key (from AI Studio), or press Enter to skip: " CRT_GEMINI_API_KEY
  echo ""
fi
if [ -n "${CRT_GEMINI_API_KEY:-}" ]; then
  mkdir -p "$HOME/.crt"
  umask 077
  printf '%s' "$CRT_GEMINI_API_KEY" > "$HOME/.crt/gemini.key"
  chmod 600 "$HOME/.crt/gemini.key"
  umask 022
  echo "    Installed to ~/.crt/gemini.key"
else
  echo "    Skipped -- bin/crt-book-game.py falls back to template questions without it."
  echo "    Re-run later with CRT_GEMINI_API_KEY=... ./install.sh to add it, or drop the"
  echo "    key straight into ~/.crt/gemini.key by hand (chmod 600)."
fi

echo ""
echo "==> Done. Reboot to test full autoboot flow: sudo reboot"
echo "    Manual test without reboot: bash $PROJECT_DIR/bin/crt-console.sh"
if [ ! -f "$HOME/.claude/.credentials.json" ]; then
  echo "    First run: 'claude' will prompt you to log in once (needs network + one-time auth)."
  echo "    (skip this next time: pre-seed CRT_CLAUDE_CREDENTIALS_PATH)"
fi
