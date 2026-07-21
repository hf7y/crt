#!/usr/bin/env python3
# Receives forwarded USB 1D-scanner reads from dexter (see
# bin/dexter-scanner-forward.ps1). The scanner is physically plugged into
# dexter (a Windows host), not this VM, so it can't be read directly here --
# dexter reads the raw HID device and POSTs each decoded line to this
# listener over the NAT port-forward set up for it (host 8993 -> guest
# 8993, see HANDOFF.md's dexter<->crt-vm access pathways section).
#
# LOG-ONLY, deliberately (2026-07-21, input-routing cleanup): every scan is
# logged unfiltered to ~/.crt/scanner.log (same spirit as ~/.crt/stt.log for
# voice) -- that log is the single source of truth for this stream.
# `bin/crt-book-console.py` tails it directly for the book-game display, and
# `bin/crt-book-answer-listen.py` correlates it against stt.log for grading.
# This used to ALSO `tmux send-keys` each scan into whatever window
# currently had focus -- SCANNER.md's "2026-07-21 late session" already
# found that path unreliable (raw scanner keystrokes land wherever tmux
# focus happens to be, not necessarily somewhere a scan should be typed) and
# pivoted book-game to read its own stdin/tail the log instead. That send-
# keys call was left in as dead-ish code after the pivot -- it still meant
# an unrelated scan could land as literal keystrokes in window 0's Claude
# pane (or wherever else had focus), a second uncontrolled escalation path
# alongside STT's already-gated one. Removed: this listener now only ever
# writes the log; nothing here can put a barcode in front of Claude.
#
# Run on crt-vm:  python3 bin/crt-scanner-feed.py
# From dexter:    POST http://<crt-vm>:8993/scan   body: {"text": "..."}
import datetime
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("CRT_SCANNER_PORT", "8993"))
LOG_PATH = os.path.expanduser("~/.crt/scanner.log")


def log_scan(text: str) -> None:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a") as f:
        f.write("%s\t%s\n" % (datetime.datetime.now().isoformat(timespec="seconds"), text))


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
    print("[crt-scanner-feed] listening on 0.0.0.0:%d, logging to %s" % (PORT, LOG_PATH))
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
