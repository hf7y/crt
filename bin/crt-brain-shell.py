#!/usr/bin/env python3
# The dexter-side half of "run Claude Code off potato" (2026-07-28) --
# successor to crt-remote-claude-bridge.py, which this replaces.
#
# WHY THIS SHAPE, AND WHY THE OLD ONE IS GONE. The bridge existed because
# mandark was a laptop with no inbound network path: it bound 127.0.0.1
# only, and potato reached it through a reverse tunnel mandark itself
# initiated outward. That whole design was a consequence of the brain host
# being intermittent and unreachable, not a property anyone wanted for its
# own sake -- see DEXTER-MOVE.md section 2, where migrating it verbatim was
# rejected precisely so a retired threat model would not be fossilized on
# an always-on box.
#
# dexter already runs sshd and potato already holds a key to it. So the
# transport is just SSH, and this program is what that key is allowed to
# run -- nothing else. The security argument the bridge made for its tiny
# two-verb protocol still holds and is deliberately kept: a compromised
# potato gets CAPTURE and SEND against ONE named tmux session, not a
# shell. That is enforced twice over:
#
#   1. authorized_keys pins this program as a forced command with
#      `restrict`, so sshd will not run anything else, will not forward
#      ports, and will not allocate a pty.
#   2. This program never execs a shell, never interpolates the request
#      into one, and passes SEND's payload to tmux as a single argv
#      element. There is no code path here that runs client-supplied text.
#
# The protocol is byte-identical to the bridge's on purpose: one request
# line in, one response body out, then close. potato's crt-secretary.py
# speaks it over an ssh pipe instead of a socket, and nothing else in that
# file had to learn where the brain lives.
#
# Usage (as a forced command -- the request arrives on stdin):
#   command="/home/zach/.local/bin/crt-brain-shell",restrict ssh-ed25519 ...
# Also:
#   crt-brain-shell --print-session   -> the tmux session name, so the
#                                        start script does not retype it
import argparse
import os
import subprocess
import sys

# The one place the session name is written down. The start script asks for
# it via --print-session and authorized_keys does not pass --session at all,
# so this default is the single source rather than a string repeated in
# three files (BUILD-DISCIPLINE: config read from one source).
DEFAULT_SESSION = os.environ.get("CRT_BRAIN_SESSION", "potato-claude")

# A capture that takes longer than this means tmux itself is wedged. The
# bridge had no timeout at all: it inherited socketserver's blocking reads,
# and a hung tmux would hold the connection open until potato's own
# SSH_CONNECT_TIMEOUT gave up. Bounding it here makes the failure ours to
# report instead of a silence potato has to infer from.
TMUX_TIMEOUT = 10


def _tmux(args):
    """Run one tmux command. Returns (rc, stdout, detail).

    A timeout is a failure with a NAME, not an exception that kills the
    connection mid-response -- potato distinguishes "reached the brain host,
    tmux refused" from "never reached it" by whether a body comes back, so
    crashing here would mislabel a wedged tmux as an unreachable dexter.
    """
    try:
        r = subprocess.run(["tmux"] + args, capture_output=True, text=True,
                           timeout=TMUX_TIMEOUT)
    except subprocess.TimeoutExpired:
        return 1, "", "tmux %s timed out after %ds" % (args[0], TMUX_TIMEOUT)
    except OSError as e:
        return 1, "", "tmux not runnable: %s" % e
    detail = (r.stderr or "").strip().replace("\n", " ")[:200]
    return r.returncode, r.stdout, detail


def capture_pane(session):
    """The pane text, or None if it could not be read.

    None vs "" matters and is potato's whole failure signal: its
    capture_pane() treats an empty body as unreadable, because a live Claude
    Code pane is never legitimately blank. Returning "" for a dead session
    would look, on the wire, exactly like a healthy but empty brain.
    """
    rc, out, detail = _tmux(["capture-pane", "-t", session, "-p", "-S", "-200"])
    if rc != 0:
        _log("CAPTURE failed: %s" % (detail or "tmux exit %d" % rc))
        return None
    return out


def send_to_claude(session, text):
    """Type text + Enter into the session. Returns (ok, detail).

    Both keystrokes are checked separately, kept from the bridge because the
    reason was earned: `-l` can deliver the literal text and succeed while
    the session dies before the newline, leaving a half-typed prompt in
    Claude's input and no reply -- the most confusing failure mode, and a
    silent one before 2026-07-25.
    """
    for keys in (["-l", text], ["Enter"]):
        rc, _, detail = _tmux(["send-keys", "-t", session] + keys)
        if rc != 0:
            return False, detail or "tmux send-keys exit %d" % rc
    return True, ""


def _log(msg):
    """Loud on dexter's side, harmless on potato's.

    stderr over an ssh pipe reaches potato's client, which ignores it -- but
    it also lands in dexter's own auth/journal context where a human
    debugging a dead console will actually look. The bridge logged nothing
    at all, so a refusing tmux left no trace on the brain host.
    """
    sys.stderr.write("[crt-brain-shell] %s\n" % msg)
    sys.stderr.flush()


def main():
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--session", default=DEFAULT_SESSION)
    p.add_argument("--print-session", action="store_true")
    args, _unknown = p.parse_known_args()

    if args.print_session:
        print(args.session)
        return 0

    # A client that tried to run a real command got refused by sshd's forced
    # command, but the attempt is worth recording -- under the old bridge
    # this could not even be expressed, so seeing it here at all is new
    # information about potato (or about whoever holds its key).
    original = os.environ.get("SSH_ORIGINAL_COMMAND", "")
    if original:
        _log("refused SSH_ORIGINAL_COMMAND=%r (forced command; ignoring)"
             % original[:200])

    line = sys.stdin.readline().rstrip("\n")

    if line == "CAPTURE":
        pane = capture_pane(args.session)
        if pane is None:
            return 1          # no body: potato reads this as unreadable
        sys.stdout.write(pane)
        return 0

    if line.startswith("SEND "):
        ok, detail = send_to_claude(args.session, line[len("SEND "):])
        if ok:
            sys.stdout.write("OK")
            return 0
        # "ERR <detail>" is the bridge's wire format, kept so potato's
        # existing "reached it but tmux refused" branch still fires.
        sys.stdout.write("ERR " + detail)
        _log("SEND failed: %s" % detail)
        return 1

    # An unrecognized verb is a bug in the caller or someone probing. The
    # bridge answered every such request with an empty body and exit 0 --
    # an exit-0 no-op that made a typo indistinguishable from a dead tmux.
    # Refuse it loudly instead; the empty body keeps potato's contract.
    _log("unknown request %r -- refusing" % line[:120])
    return 2


if __name__ == "__main__":
    sys.exit(main())
