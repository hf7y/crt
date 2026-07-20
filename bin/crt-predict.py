#!/usr/bin/env python3
# Cheap local "what did they probably just say" guesser, trained on this
# room's own history (~/.crt/stt.log). Used to flash a guess on screen the
# instant an utterance ends -- before whisper (which takes real wall-clock
# time) has actually run -- then get overwritten by the real transcription.
# This is PARKING-LOT.md's predictive-typing-then-overwrite aesthetic,
# applied to the STT step itself rather than Claude's reply, and
# PHILOSOPHY.md principle #1 (answer first, be right later) in its most
# literal form: the "answer" here is honestly just a guess, and looks like
# one, but appearing in ~0ms beats appearing in 1-3s of dead air.
#
# Deliberately NOT a real language model -- whole-utterance + bigram
# frequency counts over this room's own transcript history. Whatever this
# room says most, in this hour of the day, is a genuinely reasonable guess
# for a home console with a small repeated vocabulary (checking on jobs,
# control words, common requests) -- see STT-MECHANISM.md on how small/
# repetitive this room's real vocabulary tends to be.
#
# STATUS: NOT hardware-verified against real stt.log traffic (no VM access
# this session) -- logic is covered by tests/test_predict.py against
# synthetic log data instead.
#
# Usage:
#   crt-predict.py build     # (re)build ~/.crt/predict-model.json from stt.log
#   crt-predict.py guess     # print one guessed utterance, or "" if no model
import collections
import datetime
import json
import os
import re
import sys

STT_LOG = os.environ.get("CRT_STT_LOG", os.path.expanduser("~/.crt/stt.log"))
MODEL_PATH = os.environ.get("CRT_PREDICT_MODEL", os.path.expanduser("~/.crt/predict-model.json"))
TS_RE = re.compile(r"^(\d{2}):(\d{2}):(\d{2})")


def parse_log(path):
    """Yields (hour_of_day_or_None, text) for every real line in an
    stt.log-shaped file ("HH:MM:SS  text")."""
    entries = []
    if not os.path.exists(path):
        return entries
    with open(path) as f:
        for line in f:
            line = line.rstrip("\n")
            if "  " not in line:
                continue
            ts, text = line.split("  ", 1)
            text = text.strip()
            if not text:
                continue
            m = TS_RE.match(ts)
            hour = int(m.group(1)) if m else None
            entries.append((hour, text))
    return entries


def build_model(log_path=STT_LOG):
    entries = parse_log(log_path)
    overall = collections.Counter()
    by_hour = collections.defaultdict(collections.Counter)
    bigram = collections.defaultdict(collections.Counter)
    starters = collections.Counter()
    for hour, text in entries:
        norm = text.strip().lower()
        overall[norm] += 1
        if hour is not None:
            by_hour[hour][norm] += 1
        words = norm.split()
        if words:
            starters[words[0]] += 1
        for a, b in zip(words, words[1:]):
            bigram[a][b] += 1
    return {
        "n": len(entries),
        "overall_top": overall.most_common(20),
        "by_hour_top": {str(h): c.most_common(5) for h, c in by_hour.items()},
        "starters_top": starters.most_common(10),
        "bigram_top": {w: c.most_common(3) for w, c in bigram.items()},
    }


def save_model(model, path=MODEL_PATH):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w") as f:
        json.dump(model, f)


def load_model(path=MODEL_PATH):
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def chain_from_bigram(model, max_words=6):
    """Fallback when there's no repeated whole-utterance history yet: walk
    the most common word-to-word continuations starting from the most
    common opening word. Produces a plausible-shaped guess even from a
    small/early corpus."""
    starters = model.get("starters_top") or []
    bigram = model.get("bigram_top") or {}
    if not starters:
        return ""
    word = starters[0][0]
    out = [word]
    for _ in range(max_words - 1):
        nxt = bigram.get(word)
        if not nxt:
            break
        word = nxt[0][0]
        out.append(word)
    return " ".join(out)


def guess(model, hour=None):
    if not model or not model.get("n"):
        return ""
    if hour is not None:
        hour_top = (model.get("by_hour_top") or {}).get(str(hour))
        if hour_top:
            return hour_top[0][0]
    overall_top = model.get("overall_top")
    if overall_top:
        return overall_top[0][0]
    return chain_from_bigram(model)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "guess"
    if cmd == "build":
        model = build_model()
        save_model(model)
        sys.stderr.write("[crt-predict] built model from %d utterances -> %s\n"
                          % (model["n"], MODEL_PATH))
        return
    model = load_model()
    hour = datetime.datetime.now().hour
    sys.stdout.write(guess(model, hour))


if __name__ == "__main__":
    main()
