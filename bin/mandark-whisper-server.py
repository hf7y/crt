#!/usr/bin/env python3
# COMPAT SHIM -- the implementation moved to bin/crt-whisper-server.py (2026-07-29).
#
# This path is NOT dead and must not be deleted casually: mandark's live
# `crt-whisper-server.service` has
#   ExecStart=... /home/zach/Documents/Projects/crt/bin/mandark-whisper-server.py
# baked into its unit file (see bin/setup-mandark-whisper-persistence.sh:18).
# That unit is ACTIVE and is the console's only working STT path today, and the
# run that made this change was on dexter with no way to reach mandark to edit
# and restart the unit. Breaking a live service from a host that cannot test the
# fix is exactly the move this project keeps getting hurt by, so the old path
# keeps working instead.
#
# TO RETIRE THIS FILE, on mandark, in this order:
#   1. edit the unit's ExecStart to .../bin/crt-whisper-server.py
#   2. sudo systemctl daemon-reload && sudo systemctl restart crt-whisper-server
#   3. curl -s localhost:8991/health   -> {"ok": true, ..., "host": "mandark"}
#   4. only then delete this file and the compat test that pins it
# Steps 1-3 are what `bin/setup-mandark-whisper-persistence.sh` now writes for a
# fresh install; this shim exists only for the already-installed unit.
#
# Deliberately an exec, not an import: same PID, same signals, same systemd
# Restart= semantics, and `__main__` still runs in the real file.
import os
import sys

target = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "crt-whisper-server.py")
if not os.path.exists(target):
    sys.stderr.write(
        "mandark-whisper-server.py: shim target missing: %s\n"
        "This file is a compat shim; the real server is crt-whisper-server.py.\n"
        % target)
    sys.exit(2)

os.execv(sys.executable, [sys.executable, target] + sys.argv[1:])
