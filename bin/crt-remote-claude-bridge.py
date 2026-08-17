#!/usr/bin/env python3
# The mandark-side half of "run Claude Code off potato" (2026-07-23).
#
# THREAT MODEL / WHY THIS SHAPE, NOT A GENERIC SSH SERVER: mandark
# (a personal dev laptop) has never run an SSH server -- it has only
#   [rest: vault:crt/header-archaeology-20260817.md]
import argparse
import os
import socketserver
import subprocess


def capture_pane(session):
    r = subprocess.run(["tmux", "capture-pane", "-t", session, "-p", "-S", "-200"],
                        capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def send_to_claude(session, text):
    """Type text + Enter into the session. Returns (ok, detail).

    ok is True only if tmux accepted BOTH keystrokes (2026-07-25). It used
    to ignore both return codes and the handler replied "OK" regardless, so
    a session that had died, been renamed, or never started looked
    identical, over the socket, to one that took the message -- and
    potato's side then sat through a full wait for a reply that could not
    come. `tmux send-keys` to a missing target exits non-zero with a real
    message on stderr; that message is what the caller gets back.

    The Enter is checked separately on purpose: -l delivers the literal
    text and can succeed while the session dies before the newline, which
    leaves a half-typed prompt sitting in Claude's input and no reply --
    the most confusing of the failure modes, and silent under the old
    code."""
    for keys in (["-l", text], ["Enter"]):
        r = subprocess.run(["tmux", "send-keys", "-t", session] + keys,
                            capture_output=True, text=True)
        if r.returncode != 0:
            detail = (r.stderr or "").strip() or "tmux send-keys exit %d" % r.returncode
            return False, detail.replace("\n", " ")[:200]
    return True, ""


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        line = self.rfile.readline().decode("utf-8", errors="replace").rstrip("\n")
        session = self.server.session
        if line == "CAPTURE":
            self.wfile.write(capture_pane(session).encode("utf-8"))
        elif line.startswith("SEND "):
            ok, detail = send_to_claude(session, line[len("SEND "):])
            # "OK" is unchanged for the working case, so potato's existing
            # client keeps working; the ERR line is additive.
            self.wfile.write(b"OK" if ok else ("ERR " + detail).encode("utf-8"))
        else:
            self.wfile.write(b"")


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int,
                    default=int(os.environ.get("CRT_REMOTE_BRIDGE_PORT", "8993")))
    p.add_argument("--session",
                    default=os.environ.get("CRT_REMOTE_BRIDGE_SESSION", "potato-claude"))
    args = p.parse_args()

    server = Server(("127.0.0.1", args.port), Handler)
    server.session = args.session
    print("[crt-remote-claude-bridge] listening on 127.0.0.1:%d -> tmux session %r"
          % (args.port, args.session))
    print("[crt-remote-claude-bridge] 127.0.0.1-only, by design -- see this file's header")
    server.serve_forever()


if __name__ == "__main__":
    main()
