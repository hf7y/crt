#!/usr/bin/env python3
# Keep a nightly-batch report answerable (2026-07-25).
#
# WHY THIS EXISTS. Zach replies to these reports inline, and the reply
# arrives at the next cycle anchored by section heading plus a quoted line:
#   [rest: vault:crt/header-archaeology-20260817.md]
import re
import sys

HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")

# Fenced code blocks can legitimately contain lines starting with '#'
# (shell comments, python comments). Those are not headings.
FENCE = re.compile(r"^\s*(```|~~~)")


def headings(text):
    """[(line_no, level, raw_text)] for every real ATX heading, skipping
    anything inside a fenced code block."""
    out = []
    in_fence = False
    for i, line in enumerate(text.splitlines(), 1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = HEADING.match(line)
        if m:
            out.append((i, len(m.group(1)), m.group(2)))
    return out


def normalize(text):
    """Two headings collide if a human reading a reply anchor could not tell
    them apart. Whitespace and case are not what makes them distinct."""
    return re.sub(r"\s+", " ", text).strip().casefold()


def duplicates(text):
    """{normalized: [line_no, ...]} for every heading text used more than
    once. Level is deliberately NOT part of the key: '## Foo' and '### Foo'
    are equally ambiguous to an anchor that quotes the text."""
    seen = {}
    for line_no, _level, raw in headings(text):
        seen.setdefault(normalize(raw), []).append((line_no, raw))
    return {k: v for k, v in seen.items() if len(v) > 1}


def lint(path):
    """Returns the number of duplicated heading texts in path. Raises OSError
    up to the caller -- an unreadable report is a loud failure, not a clean
    pass, because 'no findings' and 'never looked' must not share an exit
    code (this project's signature defect; see SECRETARY.md)."""
    with open(path) as f:
        text = f.read()
    dups = duplicates(text)
    if not dups:
        print("ok - %s: every heading occurs once" % path)
        return 0
    for _key, hits in sorted(dups.items(), key=lambda kv: kv[1][0][0]):
        where = ", ".join("line %d" % n for n, _raw in hits)
        print("FAIL - %s: %r appears %d times (%s)"
              % (path, hits[0][1], len(hits), where), file=sys.stderr)
    print("FAIL - %s: a repeated heading makes an inline reply's "
          "'Section:' anchor ambiguous -- move earlier cycles to their own "
          "file and link them" % path, file=sys.stderr)
    return len(dups)


def main(argv):
    if not argv:
        print("usage: crt-report-lint.py FILE [FILE...]", file=sys.stderr)
        return 2
    bad = 0
    for path in argv:
        try:
            bad += lint(path)
        except OSError as e:
            print("FAIL - %s: %s" % (path, e), file=sys.stderr)
            return 2
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
