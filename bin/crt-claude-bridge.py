#!/usr/bin/env python3
# Mirrors the in-VM claude's actual replies into ~/.crt/thoughts.log, so
# window 1's ephemeral pretty-print pane (crt-monologue.py) shows claude's
# own responses instead of a separate external narration. Tails claude's own
# session transcript (JSONL, same format Claude Code always writes) rather
#   [rest: vault:crt/header-archaeology-20260817.md]
import glob, json, os, time

def _default_project_dir():
    project_path = os.path.expanduser(os.environ.get("CRT_PROJECT_DIR", "~/crt"))
    return "~/.claude/projects/" + project_path.replace("/", "-")

PROJECT_DIR = os.path.expanduser(os.environ.get("CRT_CLAUDE_PROJECT_DIR", _default_project_dir()))
LOG = os.path.expanduser(os.environ.get("CRT_THOUGHT_LOG", "~/.crt/thoughts.log"))
POLL = float(os.environ.get("CRT_BRIDGE_POLL", "1.0"))
STALE_SECS = float(os.environ.get("CRT_BRIDGE_STALE_SECS", "30"))
MARKER = os.environ.get("CRT_BRIDGE_MARKER", "» ")  # "» "
FALLBACK_STALE_SECS = float(os.environ.get("CRT_BRIDGE_FALLBACK_STALE_SECS", "120"))


def latest_transcript():
    files = glob.glob(os.path.join(PROJECT_DIR, "*.jsonl"))
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def _assistant_texts(entry):
    if entry.get("type") != "assistant":
        return None
    content = entry.get("message", {}).get("content", [])
    texts = [c["text"] for c in content if isinstance(c, dict) and c.get("type") == "text" and c.get("text")]
    return texts or None


def extract_marked(entry, marker=MARKER):
    """Only lines starting with `marker` are mirrored to window 1 -- see
    the MARKER FILTER note above. Marker itself is stripped."""
    texts = _assistant_texts(entry)
    if not texts:
        return None
    lines = []
    for text in texts:
        for line in text.splitlines():
            if line.startswith(marker):
                lines.append(line[len(marker):].strip())
    return " ".join(lines) if lines else None


def extract_fallback(entry):
    """Full unmarked text, no filtering -- the pre-marker-filter behavior.
    Only used once the marker convention has gone quiet for
    FALLBACK_STALE_SECS, see the FALLBACK note above."""
    texts = _assistant_texts(entry)
    return " ".join(texts) if texts else None


def choose_text(entry, last_marked, now, marker=MARKER, fallback_stale_secs=FALLBACK_STALE_SECS):
    """What (if anything) to forward for one transcript entry, and whether
    it was a marked hit. Prefers a marked line; falls back to full
    unmarked text once nothing marked has landed for fallback_stale_secs
    -- see the FALLBACK note above (dark beats flooded, but only as a last
    resort)."""
    marked = extract_marked(entry, marker)
    if marked:
        return marked, True
    if now - last_marked > fallback_stale_secs:
        return extract_fallback(entry), False
    return None, False


def write_thought(text):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    secs = int(time.time()) % 86400
    with open(LOG, "a") as f:
        f.write("%05x  %s\n" % (secs, text))


def should_switch(current, latest, last_growth, now, stale_secs=STALE_SECS):
    """Whether to abandon `current` in favor of `latest`. Sticky by design:
    a second, unrelated session appearing/ending in the same project dir
    must not steal the mirror away from window 0's own session mid-flight
    -- only reasonable when `current` itself looks dead."""
    if current is None:
        return True
    if latest == current:
        return False
    return (now - last_growth) > stale_secs


def main():
    current = None
    pos = 0
    last_growth = time.time()
    last_marked = time.time()  # optimistic start: don't flood on boot before any reply exists
    while True:
        path = latest_transcript()
        now = time.time()
        if should_switch(current, path, last_growth, now):
            current = path
            pos = os.path.getsize(path) if path else 0   # skip history on (re)attach
            last_growth = now
        if current:
            try:
                sz = os.path.getsize(current)
                if sz > pos:
                    last_growth = time.time()
                    # errors="replace": this reads a transcript file Claude
                    # Code is actively appending to, so a read can land
                    # mid-character. UnicodeDecodeError is a ValueError and
                    # the `except OSError` below would not catch it -- one
                    # torn byte would end the process that puts Claude's
                    # replies on window 1. A replacement char in one line
                    # is a far smaller loss than the mirror going dark.
                    with open(current, encoding="utf-8", errors="replace") as f:
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
                        text, was_marked = choose_text(entry, last_marked, time.time())
                        if was_marked:
                            last_marked = time.time()
                        if text:
                            write_thought(text)
            except OSError:
                pass
        time.sleep(POLL)


if __name__ == "__main__":
    main()
