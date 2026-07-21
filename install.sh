#!/usr/bin/env bash
# One-time setup on the Debian/Ubuntu VM. Installs deps, builds whisper.cpp,
# downloads a model, wires autologin on tty1, and makes tty1 boot straight
# into Claude Code + the voice-to-text feeder.
#
# Run as the user who will use the console (not root); it will sudo where needed.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_USER="$(whoami)"

echo "==> Installing packages"
sudo apt-get update
sudo apt-get install -y build-essential cmake git tmux sox alsa-utils curl openscad evtest

echo "==> Installing Claude Code CLI"
if ! command -v claude >/dev/null 2>&1; then
  curl -fsSL https://claude.ai/install.sh | bash
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
  export PATH="$HOME/.local/bin:$PATH"
else
  echo "    claude already installed, skipping"
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
echo "    First run: 'claude' will prompt you to log in once (needs network + one-time auth)."
