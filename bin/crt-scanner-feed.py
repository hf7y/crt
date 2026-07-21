#!/usr/bin/env python3
# Receives forwarded USB 1D-scanner reads from dexter (see
# bin/dexter-scanner-forward.ps1) and delivers them the same way
# stt-feed.sh delivers voice transcriptions: typed into the tmux Claude
# Code pane + Enter. The scanner is physically plugged into dexter (a
# Windows host), not this VM, so it can't be read directly here -- dexter
# reads the raw HID device and POSTs each decoded line to this listener
# over the NAT port-forward set up for it (host 8993 -> guest 8993, see
# HANDOFF.md's dexter<->crt-vm access pathways section).
#
# Every scan is logged unfiltered to ~/.crt/scanner.log first (same
# spirit as ~/.crt/stt.log for voice) so a mis-scan or barcode-format
# question can be diagnosed after the fact, before whatever filtering/
# routing logic below decides what to do with it.
#
# Run on crt-vm:  python3 bin/crt-scanner-feed.py
# From dexter:    POST http://<crt-vm>:8993/scan   body: {"text": "..."}
import datetime
import json
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("CRT_SCANNER_PORT", "8993"))
SESSION = os.environ.get("CRT_TMUX_SESSION", "claude")
PANE = os.environ.get("CRT_TMUX_PANE", "0")
LOG_PATH = os.path.expanduser("~/.crt/scanner.log")


def log_scan(text: str) -> None:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a") as f:
        f.write("%s\t%s\n" % (datetime.datetime.now().isoformat(timespec="seconds"), text))


def deliver(text: str) -> None:
    target = "%s:%s" % (SESSION, PANE)
    # Prefix so it reads distinctly from spoken/typed text in the pane --
    # a barcode is a scan event, not a sentence someone said.
    subprocess.run(["tmux", "send-keys", "-t", target, "-l", "[scan] " + text])
    subprocess.run(["tmux", "send-keys", "-t", target, "Enter"])


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # quiet; scanner.log is the record of truth

    def do_POST(self):
        if self.path != "/scan":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        try:
            data = json.loads(body or b"{}")
            text = str(data.get("text", "")).strip()
        except json.JSONDecodeError:
            text = body.decode("utf-8", "ignore").strip()

        if not text:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"error":"empty text"}')
            return

        log_scan(text)
        deliver(text)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    print("[crt-scanner-feed] listening on 0.0.0.0:%d, feeding tmux %s:%s" % (PORT, SESSION, PANE))
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
