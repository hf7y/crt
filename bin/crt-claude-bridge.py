#!/usr/bin/env python3
# Mirrors the in-VM claude's actual replies into ~/.crt/thoughts.log, so
# window 1's ephemeral pretty-print pane (crt-monologue.py) shows claude's
# own responses instead of a separate external narration. Tails claude's own
# session transcript (JSONL, same format Claude Code always writes) rather
# than screen-scraping the tmux pane -- structured and far less fragile.
#
# STATUS: written 2026-07-19, not yet run continuously/long-term verified.
import glob, json, os, time

PROJECT_DIR = os.path.expanduser(os.environ.get("CRT_CLAUDE_PROJECT_DIR",
    "~/.claude/projects/-home-zach-crt"))
LOG = os.path.expanduser(os.environ.get("CRT_THOUGHT_LOG", "~/.crt/thoughts.log"))
POLL = float(os.environ.get("CRT_BRIDGE_POLL", "1.0"))


def latest_transcript():
    files = glob.glob(os.path.join(PROJECT_DIR, "*.jsonl"))
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def extract_text(entry):
    if entry.get("type") != "assistant":
        return None
    content = entry.get("message", {}).get("content", [])
    texts = [c["text"] for c in content if isinstance(c, dict) and c.get("type") == "text" and c.get("text")]
    return " ".join(texts) if texts else None


def write_thought(text):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    secs = int(time.time()) % 86400
    with open(LOG, "a") as f:
        f.write("%05x  %s\n" % (secs, text))


def main():
    current = None
    pos = 0
    while True:
        path = latest_transcript()
        if path != current:
            current = path
            pos = os.path.getsize(path) if path else 0   # skip history on (re)attach
        if current:
            try:
                sz = os.path.getsize(current)
                if sz > pos:
                    with open(current) as f:
                        f.seek(pos)
                        chunk = f.read()
                        pos = f.tell()
                    for ln in chunk.splitlines():
                        if not ln.strip():
                            continue
                        try:
                            entry = json.loads(ln)
                        except json.JSONDecodeError:
                            continue
                        text = extract_text(entry)
                        if text:
                            write_thought(text)
            except OSError:
                pass
        time.sleep(POLL)


if __name__ == "__main__":
    main()
