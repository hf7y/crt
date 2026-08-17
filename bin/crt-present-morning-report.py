#!/usr/bin/env python3
# Pure-code (zero Claude calls) presenter for the scheduler's cross-project
# morning report -- parses bin/morning-report.sh's own output and decides
# what becomes a CRT one-liner vs. a printer page. See
# MORNING-REPORT-PRESENTATION.md for the full design/contract this
#   [rest: vault:crt/header-archaeology-20260817.md]
import os
import re
import subprocess
import sys

DEFAULT_SCRIPT = os.path.expanduser(
    "~/Documents/Project Archive/scheduler/bin/morning-report.sh")
SCRIPT = os.environ.get("CRT_MORNING_REPORT_SCRIPT", DEFAULT_SCRIPT)
SCREEN_WIDTH = int(os.environ.get("CRT_PAGER_WIDTH", "40"))

# morning-report.sh's own section-header shape, verbatim from its source:
# a line of "════"s, "  <name>", another line of "════"s.
HEADER_RE = re.compile(r"^═+\n {2}(.+?)\n═+\n", re.MULTILINE)


def parse_sections(text):
    """Splits morning-report.sh's stdout into named sections. Returns a
    list of {name, headline, body} in the order they appeared. Pure --
    no I/O."""
    matches = list(HEADER_RE.finditer(text))
    sections = []
    for i, m in enumerate(matches):
        name = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip("\n")
        sections.append({"name": name, "headline": _headline(body), "body": body})
    return sections


def _headline(body):
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        line = line.lstrip("#").strip()
        return line
    return ""


def format_screen_line(section, width=SCREEN_WIDTH):
    line = "%s: %s" % (section["name"], section["headline"])
    if len(line) > width:
        line = line[:max(0, width - 3)].rstrip() + "..."
    return line


FETCH_TIMEOUT = float(os.environ.get("CRT_MORNING_REPORT_TIMEOUT", "20"))


def fetch_raw(script=SCRIPT):
    # 2026-07-20: morning-report.sh was independently observed to hang
    # (unrelated to this file -- confirmed by running it standalone) on
    # this same evaluation, plausibly a slow/unreachable per-project
    # DEPLOY_FRESH_CMD probe (e.g. a network check against an
    #   [rest: vault:crt/header-archaeology-20260817.md]
    try:
        r = subprocess.run(["bash", script], capture_output=True, text=True,
                            timeout=FETCH_TIMEOUT)
        return r.stdout
    except subprocess.TimeoutExpired:
        sys.stderr.write(
            "[crt-present-morning-report] morning-report.sh did not finish "
            "within %ss -- returning nothing rather than hanging.\n" % FETCH_TIMEOUT)
        return ""


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "screen"
    raw = fetch_raw()
    sections = parse_sections(raw)

    if cmd == "screen":
        if not sections:
            print("Nothing to report.")
            return
        for s in sections:
            print(format_screen_line(s))
        return

    if cmd == "print-all":
        print(raw.strip())
        return

    if cmd == "print":
        if len(sys.argv) < 3:
            sys.stderr.write("usage: crt-present-morning-report.py print <section-name>\n")
            sys.exit(2)
        target = sys.argv[2].lower()
        for s in sections:
            if s["name"].lower() == target:
                print(s["body"])
                return
        sys.stderr.write("[crt-present-morning-report] no section named %r\n" % sys.argv[2])
        sys.exit(1)

    sys.stderr.write("usage: crt-present-morning-report.py <screen|print <name>|print-all>\n")
    sys.exit(2)


if __name__ == "__main__":
    main()
