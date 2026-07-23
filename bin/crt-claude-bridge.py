#!/usr/bin/env python3
# Mirrors the in-VM claude's actual replies into ~/.crt/thoughts.log, so
# window 1's ephemeral pretty-print pane (crt-monologue.py) shows claude's
# own responses instead of a separate external narration. Tails claude's own
# session transcript (JSONL, same format Claude Code always writes) rather
# than screen-scraping the tmux pane -- structured and far less fragile.
#
# STATUS: written 2026-07-19, not yet run continuously/long-term verified.
#
# BUG FOUND LIVE 2026-07-23: PROJECT_DIR's default used to hardcode
# "-home-zach-crt" (a leftover username from an earlier setup) -- on this
# box (user vkv, home /home/vkv/crt) that directory has never existed, so
# latest_transcript() always returned None and this script has silently
# forwarded ZERO Claude replies to window 1 since the migration to this
# hardware. Now derives the real Claude Code project-transcript directory
# name from the actual project path at runtime (Claude Code's own
# convention: '/'->'-', e.g. /home/vkv/crt -> -home-vkv-crt) instead of
# hardcoding any one user's path, so this can't go stale again the next
# time this runs as a different user/home.
#
# BUG FOUND LIVE 2026-07-23 (#2): "always follow whichever *.jsonl in the
# project dir has the latest mtime" assumed exactly one live Claude Code
# session ever exists for this project at a time. False in practice -- a
# plain-ssh session (outside tmux entirely) ran concurrently with window
# 0's tmux session for ~20 minutes tonight. Whichever session's file
# happened to be newest-by-mtime at any given poll flip-flopped `current`
# back and forth, and EVERY flip resets `pos` to the new file's current
# size (by design, to skip a brand-new session's irrelevant backlog) --
# so window 0's own replies got silently skipped whenever the other
# session's file was even momentarily "latest". Fix: once locked onto a
# transcript, stay locked onto it regardless of what else is newest --
# only fail over once the current file has gone quiet for STALE_SECS
# (real signal a session actually ended), not on every mtime race.
#
# MARKER FILTER added 2026-07-23, per Zach: forwarding EVERY assistant text
# block flooded window 1's tiny 40x15 pane with long technical/diagnostic
# writeups, drowning out the short in-character lines it's actually for.
# A prompt-level rule ("remember to keep window 1 flavorful") isn't durable
# -- a fresh instance won't know it, and mid-investigation the model won't
# reliably self-censor. So this is enforced mechanically instead: only
# lines that start with MARKER get forwarded (marker stripped); everything
# else -- the default for ordinary prose -- never reaches window 1 at all.
# CLAUDE.md documents the convention for future instances.
#
# FALLBACK added 2026-07-23, per Zach's correction: a permanently dark
# window 1 (marker convention lapses over a long session, nobody notices)
# is a WORSE failure mode than the original flooding problem -- flooding at
# least proves the mirror is alive. So the marker is a preference, not the
# only path: if no marked line has come through for FALLBACK_STALE_SECS,
# stop trusting the marker and forward full unmarked text again (degrading
# back to the pre-marker-filter behavior) until a marked line reappears.
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
