#!/usr/bin/env python3
# Decide WHERE the console's Claude brain should run, at the moment a wake
# actually fires -- the small pure decision at the center of the
# "screensaver at idle, no Claude resident to save RAM; on wake reach for
# mandark, else fall back onsite, else nothing" design (see POTATO.md).
#
# potato is a 1GB Pi 3B+ and Claude Code was ~37% of its RAM
# (ARCHITECTURE-REVIEW-2026-07-23.md), so the win is: hold NO brain while
# the potato screensaver is up, and only choose one when someone speaks
# the wake word. This module is just the chooser -- it does not itself
# spawn or tunnel anything (a supervisor does that; see POTATO.md's
# "remaining live wiring" note). Kept pure + CLI-thin so it's fully
# offline-testable (tests/test_wake_router.py); the only impure part is
# the optional live socket probe, isolated in probe_bridge().
#
# Decision, in order:
#   mandark ON  + reachable        -> "remote"  (0 RAM on potato)
#   mandark ON  + unreachable      -> fall back: local if available else "none"
#   mandark OFF                    -> local if available else "none"
# "none" means: woken, but no brain available -- the caller should give a
# short honest earcon/line ("can't reach my brain right now"), NOT silence.
import argparse
import json
import os
import socket
import subprocess
import sys

DEFAULT_PORT = int(os.environ.get("CRT_MANDARK_PORT", "8993"))

REMOTE = "remote"
LOCAL = "local"
NONE = "none"


def decide_brain(mandark_on, mandark_reachable, local_available):
    """Pure core. All three args are plain bools.

    mandark_on         -- is the operator's toggle set to route to mandark?
    mandark_reachable  -- did a live probe of the bridge just succeed?
    local_available    -- can potato run a local Claude right now (creds
                          present, enough free RAM, whisper reachable)?
    """
    if mandark_on and mandark_reachable:
        return REMOTE
    # mandark off, or configured-on but currently down -> onsite fallback.
    if local_available:
        return LOCAL
    return NONE


def explain(choice):
    return {
        REMOTE: "brain: mandark (remote, no RAM cost on potato)",
        LOCAL: "brain: local onsite Claude (mandark unavailable/off)",
        NONE: "brain: none available -- give a short honest reply, not silence",
    }[choice]


def probe_bridge(port, timeout=3.0):
    """Live reachability check, mirroring crt-secretary.py's _bridge_request
    exactly (send CAPTURE, expect a non-empty pane). Returns True only if
    the bridge actually answered. Never raises."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as s:
            s.sendall(b"CAPTURE\n")
            s.shutdown(socket.SHUT_WR)
            data = b""
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                data += chunk
        return bool(data.strip())
    except OSError:
        return False


def mandark_configured_on():
    """Read the same signal crt-console.sh acts on: CRT_CLAUDE_REMOTE_PORT
    in the environment (set by ~/.crt/mandark.conf via crt-mandark.sh). A
    real port = on; 0/unset = off. Returns (on: bool, port: int)."""
    raw = os.environ.get("CRT_CLAUDE_REMOTE_PORT", "")
    try:
        port = int(raw) if raw else 0
    except ValueError:
        port = 0
    return (port != 0, port or DEFAULT_PORT)


def probe_ssh(host, timeout=6.0):
    """Live reachability check for the SSH-direct brain (2026-07-28).

    The ssh sibling of probe_bridge(), and the same standard: it sends the
    real CAPTURE and demands a non-empty pane back. Deliberately NOT a ping
    or a TCP connect -- dexter answering on port 2223 proves only that a
    daemon is up, and the failure this probe exists to catch is a dexter
    that is perfectly reachable with its potato-claude tmux session dead.
    That state passes every cheaper check and produces a console that wakes,
    routes "remote", and then hears nothing.
    """
    if not host:
        return False
    try:
        r = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=%d" % max(1, int(timeout)),
             host],
            input="CAPTURE\n", capture_output=True, text=True, timeout=timeout + 4)
    except (subprocess.TimeoutExpired, OSError):
        return False
    return bool(r.stdout.strip())


def brain_configured_on():
    """Which remote brain is configured, if any: (mode, target).

    mode is "ssh", "port" or None. Mirrors crt-secretary.py's brain_mode()
    precedence exactly -- ssh wins -- because a router that disagrees with
    the thing it routes FOR is worse than no router. mandark_configured_on()
    is kept below, unchanged, as the port-mode half.
    """
    host = os.environ.get("CRT_CLAUDE_SSH_HOST", "").strip()
    if host:
        return "ssh", host
    on, port = mandark_configured_on()
    return ("port", port) if on else (None, None)


def local_claude_available():
    """Heuristic, deliberately conservative: a local brain is 'available'
    only if Claude Code credentials exist on this box. RAM/whisper checks
    are left to the supervisor that actually spawns it -- this module only
    answers 'could we, in principle'. Override with CRT_LOCAL_CLAUDE=0/1
    for testing or to force the decision."""
    forced = os.environ.get("CRT_LOCAL_CLAUDE")
    if forced in ("0", "1"):
        return forced == "1"
    creds = os.path.expanduser("~/.claude/.credentials.json")
    return os.path.exists(creds)


def main(argv=None):
    p = argparse.ArgumentParser(description="Decide where the Claude brain runs on wake.")
    p.add_argument("--json", action="store_true", help="emit JSON instead of a word")
    p.add_argument("--no-probe", action="store_true",
                    help="skip the live bridge probe (assume unreachable)")
    args = p.parse_args(argv)

    mode, target = brain_configured_on()
    on = mode is not None
    if not on or args.no_probe:
        reachable = False
    elif mode == "ssh":
        reachable = probe_ssh(target)
    else:
        reachable = probe_bridge(target)
    local = local_claude_available()
    choice = decide_brain(on, reachable, local)

    if args.json:
        _, port = mandark_configured_on()
        print(json.dumps({
            "choice": choice,
            "brain_mode": mode,
            "brain_target": target,
            # The mandark_* keys predate the dexter move and are kept so
            # existing consumers/tests do not break. In ssh mode they
            # describe the port-mode half only, which is now off -- read
            # brain_mode/brain_target for the truth.
            "mandark_on": on and mode == "port",
            "mandark_port": port,
            "mandark_reachable": reachable and mode == "port",
            "local_available": local,
            "explain": explain(choice),
        }))
    else:
        print(choice)
    return 0


if __name__ == "__main__":
    sys.exit(main())
