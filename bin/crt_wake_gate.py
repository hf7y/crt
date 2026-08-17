#!/usr/bin/env python3
# "Was this utterance addressed to the console?" -- one answer, for the two
# processes that both read ~/.crt/stt.log (2026-07-25, fourteenth cycle).
#
# WHY THIS EXISTS. crt-stt-solo.py writes EVERY recognized utterance to
#   [rest: vault:crt/header-archaeology-20260817.md]
import importlib.util
import os
import re

_BIN_DIR = os.path.dirname(os.path.abspath(__file__))


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_BIN_DIR, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Loaded by path, not by plain `import`: every caller of this module is
# itself loaded by spec_from_file_location, which does not put bin/ on
# sys.path. Same idiom crt-stt-training-merge.py already uses.
_config = _load("crt_config_for_wake_gate", "crt_config.py")
_fixups_store = _load("crt_fixups_store_for_wake_gate", "crt_fixups_store.py")

WAKE_WORD_DEFAULT = "claude"


def wake_word(env=None):
    """The wake word in force, lowercased. Same env var and default
    crt-stt-solo.py has always used -- both processes read it from the
    environment crt-console.sh hands every window, so they cannot disagree
    unless someone sets it for one tmux window only."""
    env = os.environ if env is None else env
    return env.get("CRT_WAKE_WORD", WAKE_WORD_DEFAULT).lower()


def tokenize(text):
    """Word characters only, never str.split(). Whisper output rarely
    carries reliable punctuation, and a stray comma ("hey claude, run the
    tests") must not defeat the match."""
    return re.findall(r"[a-z0-9']+", text.lower())


def contains_phrase(words, phrase):
    """Whole-word containment: `phrase` (space-separated) must appear as a
    contiguous run of whole words in `words`, not as a bare substring --
    else a fixup fragment like "slide" would false-positive inside an
    unrelated word like "landslide"."""
    phrase_words = phrase.split()
    n = len(phrase_words)
    return any(words[i:i + n] == phrase_words for i in range(len(words) - n + 1))


def live_fixups(path=None):
    """The fixups on disk right now, minus the file's own "_comment" doc
    key. Tolerant of a missing/malformed file (crt_fixups_store.read's
    contract): the gate degrades to exact-word matching, it never fails
    closed and never raises into a caller's loop."""
    path = path or _config.fixups_path()
    return {k: v for k, v in _fixups_store.read(path).items()
            if not str(k).startswith("_")}


def addressed_to_console(text, word=None, fixups=None):
    """True if `text` was addressed to the console: the wake word appears as
    a whole word, or a stt-fixups.json fragment whose learned intent IS the
    wake word appears.

    `fixups=None` means read the live file. crt-stt-solo.py always passes an
    explicit dict (it holds a change-reporting view of the same file, see
    its FixupsFile) -- so its behaviour through this function is exactly
    what it was when the logic lived there."""
    word = wake_word() if word is None else word
    if fixups is None:
        fixups = live_fixups()
    words = tokenize(text)
    if word in words:
        return True
    return any((info or {}).get("intent") == word and contains_phrase(words, fragment)
               for fragment, info in fixups.items())
