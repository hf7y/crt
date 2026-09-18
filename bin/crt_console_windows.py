#!/usr/bin/env python3
# Which tmux windows crt-console.sh starts, and which of those a changed
# file would affect -- read from the launch script itself (crt-pull.sh,
# crt#325) so the map can never drift the way a hand-maintained copy of
# crt-console.sh's window list would.
import re
import sys


def parse_windows(script_text):
    """[(window_name, launch_command), ...] from a crt-console.sh source.

    The launch command is always the LAST quoted argument on a `tmux
    new-window`/`new-session` line -- earlier ones are `-t`/`-c` targets
    (e.g. "$SESSION", "$BIN_DIR"), not the command itself.
    """
    joined = re.sub(r"\\\n[ \t]*", " ", script_text)
    windows = []
    for line in joined.splitlines():
        if not re.search(r"tmux new-(?:window|session)\b", line):
            continue
        quotes = re.findall(r'"((?:[^"\\]|\\.)*)"', line)
        if not quotes:
            continue
        name_m = re.search(r"-n\s+(\S+)", line)
        windows.append((name_m.group(1) if name_m else "0", quotes[-1]))
    return windows


def affected_windows(changed_files, windows):
    basenames = {f.rsplit("/", 1)[-1] for f in changed_files if f.strip()}
    return [name for name, cmd in windows if any(b in cmd for b in basenames)]


def main(argv):
    if "--console" not in argv:
        print("usage: crt_console_windows.py --console PATH < changed-files", file=sys.stderr)
        return 2
    console_path = argv[argv.index("--console") + 1]
    with open(console_path) as fh:
        windows = parse_windows(fh.read())
    changed = [line.strip() for line in sys.stdin if line.strip()]
    for name in affected_windows(changed, windows):
        print(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
