#!/usr/bin/env bash
# Daily mechanical hardware-verification pass on crt-vm. Plain script, no
# LLM call -- everything here is presence checks and exit codes, not
# judgment, so a `claude -p` invocation (the original design in VM-JOBS.md)
# was pure overhead. Reworked 2026-07-20 at Zach's prompting ("can't this
# be done without claude?"). If a future check genuinely needs interpretation
# (prose, a judgment call), that's a signal to route it to the interactive
# tier instead of growing this script into an agent again.
#
# Verify, don't build, don't judge sound quality -- report present/absent
# and exit codes only. Run via systemd/crt-vm-hardware-check.timer.
set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT_DIR="$HOME/reports/crt"
TODAY="$(date +%Y-%m-%d)"
REPORT="$REPORT_DIR/$TODAY.md"
mkdir -p "$REPORT_DIR"

{
  echo "## VM hardware check — $(date '+%Y-%m-%d %H:%M')"
  echo

  echo "### Offline test suite"
  if [ -f "$PROJECT_DIR/tests/run_tests.sh" ]; then
    if out=$(cd "$PROJECT_DIR" && bash tests/run_tests.sh 2>&1); then
      echo "PASS"
    else
      echo "FAIL"
      echo '```'
      echo "$out" | tail -20
      echo '```'
    fi
  else
    echo "tests/run_tests.sh not present (repo not synced?)"
  fi
  echo

  echo "### Device presence"
  echo "aplay -L:"; echo '```'; aplay -L 2>&1 | head -20; echo '```'
  echo "arecord -l:"; echo '```'; arecord -l 2>&1; echo '```'

  whisper_bin="$(command -v whisper-cli || command -v main 2>/dev/null || true)"
  if [ -n "${CRT_WHISPER_SERVER:-}" ]; then
    if curl -sf -o /dev/null --max-time 3 "$CRT_WHISPER_SERVER"; then
      echo "- whisper server ($CRT_WHISPER_SERVER): reachable"
    else
      echo "- whisper server ($CRT_WHISPER_SERVER): unreachable"
    fi
  elif [ -n "$whisper_bin" ]; then
    echo "- whisper.cpp binary: present ($whisper_bin)"
  else
    echo "- whisper backend: ABSENT (no CRT_WHISPER_SERVER, no local binary)"
  fi

  for bin in piper espeak-ng sox catprint; do
    if command -v "$bin" >/dev/null 2>&1; then
      echo "- $bin: present"
    else
      echo "- $bin: ABSENT"
    fi
  done

  if [ -n "${CRT_HOOK_DEVICE:-}" ]; then
    if [ -e "/dev/input/by-id/$CRT_HOOK_DEVICE" ]; then
      echo "- hookswitch device ($CRT_HOOK_DEVICE): present"
    else
      echo "- hookswitch device ($CRT_HOOK_DEVICE): ABSENT"
    fi
  else
    echo "- hookswitch device: CRT_HOOK_DEVICE not set, skipped"
  fi
  echo

  echo "### Audio scripts (exit codes only, not sound quality)"
  if [ -x "$PROJECT_DIR/bin/crt-earcon.sh" ]; then
    for tone in bait question success ack oops; do
      if "$PROJECT_DIR/bin/crt-earcon.sh" "$tone" >/tmp/earcon-$tone.log 2>&1; then
        echo "- earcon $tone: rc=0"
      else
        echo "- earcon $tone: rc=$? (see /tmp/earcon-$tone.log)"
      fi
    done
  else
    echo "- crt-earcon.sh not present/executable"
  fi

  if [ -x "$PROJECT_DIR/bin/crt-tts.py" ]; then
    if "$PROJECT_DIR/bin/crt-tts.py" "hardware check" >/tmp/tts-check.log 2>&1; then
      echo "- crt-tts.py: rc=0"
    else
      echo "- crt-tts.py: rc=$? (see /tmp/tts-check.log)"
    fi
  fi

  if [ -f "$PROJECT_DIR/bin/crt-sideband.sh" ]; then
    if (CRT_SIDEBAND_TEST_MODE=1 source "$PROJECT_DIR/bin/crt-sideband.sh"; ensure_tone_wav listening "180 0 0.03") >/tmp/sideband-check.log 2>&1; then
      echo "- crt-sideband.sh ensure_tone_wav: rc=0"
    else
      echo "- crt-sideband.sh ensure_tone_wav: rc=$? (see /tmp/sideband-check.log)"
    fi
  fi
  echo

  echo "### Display calibration"
  if [ -x "$PROJECT_DIR/bin/crt-calibrate-display.py" ]; then
    echo '```'
    "$PROJECT_DIR/bin/crt-calibrate-display.py" show 2>&1
    echo '```'
  fi
  echo

} >> "$REPORT"

cp "$REPORT" "$REPORT_DIR/LATEST.md"
echo "wrote $REPORT"
