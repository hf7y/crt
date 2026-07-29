#!/bin/bash
# Stand up bin/crt-whisper-server.py on dexter, so potato's ears stop depending
# on mandark being awake. Run this ON dexter. Needs sudo.
#
# WHY THIS EXISTS (2026-07-29). FOCUS.md's "the brain moved to dexter, the EARS
# did not" item described this as "a deploy-and-repoint, not a build", on the
# premise that `bin/dexter-whisper-server.py` already existed. It did not --
# `3dee2d5` deleted it in 2026-07-24's refactor sweep, back when dexter was
# legacy. Probed first-hand on dexter the same night, the premise was wrong in a
# second way too: dexter has no Python packaging toolchain at all. So the
# preflight below is not boilerplate; every check in it is a thing that was
# actually missing on the real box.
#
# PREFLIGHT FINDINGS, dexter, 2026-07-29 (`# verified 2026-07-29 via` the
# commands each check runs):
#   - python3 is 3.14.4                      -> newest wheels may not exist yet
#   - `python3 -m pip` -> No module named pip -> python3-pip NOT installed
#   - `import ensurepip` -> ModuleNotFoundError -> python3-venv NOT installed
#   - no nvidia-smi                          -> CPU path (int8) is correct here
#   - 16 cores, 953G free on /               -> capacity is not the constraint
#
# The apt step is the reason this file is not run by an unattended pass: it
# needs sudo that a nightly job does not have, and it is machine-scoped config
# on a SHARED host. Whoever runs it owes senechal a note -- and note that
# `notify-senechal` itself is MISSING on dexter as of 2026-07-29, which is
# filed in scheduler's BLOCKERS.md under ## crt.
set -euo pipefail

VENV="${CRT_WHISPER_VENV:-$HOME/.venvs/crt-whisper-server}"
REPO="${CRT_REPO_DIR:-$HOME/crt}"
SERVER="$REPO/bin/crt-whisper-server.py"
PORT="${CRT_WHISPER_PORT:-8991}"

die() { printf '\n[setup-dexter-whisper] FATAL: %s\n' "$*" >&2; exit 1; }
note() { printf '[setup-dexter-whisper] %s\n' "$*"; }

# ---- preflight: fail loud and specific, never exit 0 having done nothing ----
[ -f "$SERVER" ] || die "server not found at $SERVER
  Set CRT_REPO_DIR to the checkout root. This script deploys the repo's
  own file; it does not carry a copy."

command -v python3 >/dev/null || die "no python3 on PATH"
PYVER="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
note "python3 is $PYVER"

if ! python3 -c 'import ensurepip' 2>/dev/null; then
  die "python3 has no ensurepip, so 'python3 -m venv' cannot bootstrap pip.
  On dexter this was the actual blocker on 2026-07-29. Fix, then re-run:
      sudo apt install python3-venv python3-pip
  (python3-pip candidate was 25.1.1+dfsg-1ubuntu2, not installed.)"
fi

# faster-whisper's real weight is ctranslate2, which ships binary wheels per
# CPython version. On a very new interpreter there may be no wheel yet, and pip
# then tries a source build that fails deep in CMake with an error that looks
# nothing like the actual cause. Say the actual cause up front.
case "$PYVER" in
  3.9|3.10|3.11|3.12|3.13) : ;;
  *) note "WARNING: python $PYVER is outside ctranslate2's usual wheel range."
     note "         If pip below falls back to a source build, do NOT debug"
     note "         CMake -- install a supported interpreter instead:"
     note "             sudo apt install python3.12 python3.12-venv"
     note "             CRT_WHISPER_PY=python3.12 $0" ;;
esac
PY="${CRT_WHISPER_PY:-python3}"

# ---- venv + deps ----
if [ ! -x "$VENV/bin/python" ]; then
  note "creating venv at $VENV using $PY"
  "$PY" -m venv "$VENV"
fi
note "installing faster-whisper + flask"
"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install faster-whisper flask

# ---- prove it loads BEFORE installing a unit that would just crashloop ----
note "loading the model once to warm the cache and prove the install"
CRT_WHISPER_TAG=dexter "$VENV/bin/python" - <<'PY'
import os
from faster_whisper import WhisperModel
size = os.environ.get("CRT_WHISPER_MODEL_SIZE", "base.en")
WhisperModel(size, device="cpu", compute_type="int8")
print("[setup-dexter-whisper] model %s loaded OK" % size)
PY

# ---- LAN port + unit ----
sudo ufw allow "$PORT"/tcp comment 'crt whisper server (LAN STT, dexter)'

sudo tee /etc/systemd/system/crt-whisper-server.service > /dev/null <<EOF
[Unit]
Description=crt console whisper transcription server (dexter)
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$REPO
Environment=CRT_WHISPER_TAG=dexter
Environment=CRT_WHISPER_PORT=$PORT
ExecStart=$VENV/bin/python $SERVER
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now crt-whisper-server.service
sudo systemctl status crt-whisper-server.service --no-pager

# ---- witness, not exit code: the health endpoint must name THIS host ----
note "waiting for /health"
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:$PORT/health" 2>/dev/null | grep -q '"host": *"dexter"'; then
    note "OK -- /health reports host=dexter"
    note "NEXT, and deliberately NOT done here: repoint the console."
    note "  crt-console.sh's CRT_WHISPER_SERVER default still points at"
    note "  http://192.168.0.27:8991 (mandark). Flipping a live console"
    note "  default is a [hw] act -- do it with the handset in reach."
    exit 0
  fi
  sleep 1
done
die "service came up but /health never reported host=dexter within 30s.
  Check: sudo journalctl -u crt-whisper-server -n 50 --no-pager"
