#!/usr/bin/env python3
# The "potato game" (filed in FOCUS.md 2026-07-23, built same night): an
# interactive calibration session, not a background service. Run it in a
# tmux window, say the wake word (or whatever else it prompts for) into
# the real mic, and watch the words STT actually heard splash around an
# ASCII potato, sized/colored by similarity to the target word --
# reuses crt-wake-pool.py's closest_pool_word() (difflib.SequenceMatcher),
# which per its OWN header comment was built "2026-07-21, calibration-game
# pass" -- this game is the thing that comment was anticipating, just
# built two days later.
#
# Two rounds:
#   wake     -- say the wake word repeatedly; each STT-recognized word
#               gets scored against it and splashed. At the end, offers
#               to save recurring near-misses into stt-fixups.json as
#               CONFIRMED aliases (a live human-in-the-loop round IS the
#               confirmation stt-fixups.json's tiers otherwise wait on).
#   earcon   -- plays each known output device's tone in turn and asks
#               you to confirm (by typing, not voice -- avoids a circular
#               "did the mic hear the beep" dependency) which device it
#               came from, so device routing can be re-verified any time
#               the hardware changes without a hands-on SSH session. Each
#               verdict is appended to CRT_EARCON_ROUTING_LOG (default
#               ~/.crt/earcon-routing.jsonl) -- the answer is the point of
#               the round, and it used to live only in the scrollback. A
#               tone that fails to PLAY is reported as that, and not put to
#               you as a question you cannot honestly answer.
#
# Reads ~/.crt/stt.log the same way crt-monologue.py does -- tails new
# lines, doesn't touch the live capture process at all (crt-stt-solo.py
# remains the sole mic reader; this is a passive downstream consumer of
# its already-unfiltered log, same posture as crt-book-answer-listen.py).
#
# CRT-safe colors only (CLAUDE.md hard rule): 33/35/36/37 plus dim/bold,
# never 31/32/34/91/92/94.
import difflib
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time

BIN_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(BIN_DIR)

_wp_spec = importlib.util.spec_from_file_location("crt_wake_pool", os.path.join(BIN_DIR, "crt-wake-pool.py"))
wake_pool = importlib.util.module_from_spec(_wp_spec)
_wp_spec.loader.exec_module(wake_pool)

_cfg_spec = importlib.util.spec_from_file_location(
    "crt_config_for_calibration_game", os.path.join(BIN_DIR, "crt_config.py"))
crt_config = importlib.util.module_from_spec(_cfg_spec)
_cfg_spec.loader.exec_module(crt_config)

_store_spec = importlib.util.spec_from_file_location(
    "crt_fixups_store_for_calibration_game", os.path.join(BIN_DIR, "crt_fixups_store.py"))
fixups_store = importlib.util.module_from_spec(_store_spec)
_store_spec.loader.exec_module(fixups_store)

_guard_spec = importlib.util.spec_from_file_location(
    "crt_loop_guard_for_calibration_game", os.path.join(BIN_DIR, "crt_loop_guard.py"))
loop_guard = importlib.util.module_from_spec(_guard_spec)
_guard_spec.loader.exec_module(loop_guard)

STT_LOG = os.path.expanduser(os.environ.get("CRT_STT_LOG", "~/.crt/stt.log"))
FIXUPS_PATH = crt_config.fixups_path()   # both spellings, one answer
EARCON_BIN = os.path.join(BIN_DIR, "crt-earcon.sh")
# Where the earcon round's verdicts go, so they outlive the tmux scrollback.
ROUTING_LOG = os.path.expanduser(
    os.environ.get("CRT_EARCON_ROUTING_LOG", "~/.crt/earcon-routing.jsonl"))

# CRT-safe palette only -- see CLAUDE.md's hard rule (never 31/32/34/91/92/94).
DIM, BRIGHT, RESET = "\033[2m", "\033[1m", "\033[0m"
YELLOW, MAGENTA, CYAN, WHITE = "\033[33m", "\033[35m", "\033[36m", "\033[37m"

# Braille-art potato, Zach's own drawing (2026-07-23), 30 chars wide.
POTATO = """
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣀⣠⠤⠴⠒⠋⠉⠉⠉⠉⠙⠒⠲⠤⢴⣤⣄⠀⠀⠀
⠀⠀⠀⠀⠀⠀⢀⣀⡴⠋⠁⠀⠀⠳⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠉⠳⡄⠀
⠀⠀⠀⢀⠴⠊⠁⢸⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠘⠆⠘⡄
⢀⠜⠁⠀⠀⠀⠀⠑⠀⠀⠀⠀⠀⢸⠓⡄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⡤⠀⢱
⢀⠎⠀⠀⠀⠀⠀⡤⣤⡀⠀⠀⠀⠀⠀⠉⠀⠀⠀⠀⠀⢀⠀⠀⠀⠀⠀⠀⠀⢸
⡎⠀⠀⠀⠀⠀⠀⠈⠒⠣⠀⠀⠀⠄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠠⠄⢀⣀⣠⠏
⣧⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⠀⠀⠀⠀⠀⠀⣨⠁⠀
⡟⠄⠀⠀⠀⠀⠀⠀⠀⠀⠀⢠⠀⠀⠀⠀⠀⠀⠀⠈⠛⠃⠀⠀⠀⣠⡾⠃⠀⠀
⢱⡈⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠑⠠⡄⠀⠀⠀⠀⠀⢀⣠⠀⣀⡴⠋⠀⠀⠀⠀
⠀⠑⢤⣀⠀⠀⣖⡆⠀⠀⠀⢄⡀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣠⠏⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠈⠙⠒⠢⠤⠤⣄⣀⣠⣤⣬⠶⠶⠦⠤⠶⠖⠚⠋⠀⠀⠀⠀⠀⠀⠀⠀
"""


def color_for_ratio(ratio):
    """Brightness/color scales with similarity -- dim white for a near
    miss, bright yellow for a near-exact match. Four bands, CRT-safe
    colors only."""
    if ratio >= 0.85:
        return BRIGHT + YELLOW
    if ratio >= 0.65:
        return MAGENTA
    if ratio >= 0.45:
        return CYAN
    return DIM + WHITE


def tail_new_lines(path, from_pos):
    """Returns (new_lines, new_pos). Missing file -> ([], from_pos),
    tolerant same as every other log reader in this project.

    errors="replace", not strict. This races crt-stt-solo.py appending, so
    it can land inside a multi-byte character a writer's buffer split across
    two flushes -- and what it reads is TRANSCRIBED SPEECH, so accented
    names and whisper's smart quotes are ordinary content here, not an edge
    case. Strict decoding raises UnicodeDecodeError, a ValueError, NOT
    caught by the `except OSError` below; raised in Tailer's thread it kills
    the thread and nothing else, so the game goes on prompting while it has
    stopped listening (measured: one torn byte, and every later word is
    lost, "Nothing worth saving", round over). ae54ef4 fixed exactly this
    for window 1 and swept four readers; this one reads the same stt.log the
    same way and was missed.

    A file that SHRANK is a file that was replaced or truncated: seek back
    to the start rather than sit past the new end forever, the same one line
    crt-monologue.py's loop has."""
    try:
        if os.path.getsize(path) < from_pos:
            from_pos = 0
        with open(path, encoding="utf-8", errors="replace") as f:
            f.seek(from_pos)
            chunk = f.read()
            pos = f.tell()
    except OSError:
        return [], from_pos
    lines = [ln.split("  ", 1)[-1] for ln in chunk.splitlines() if ln.strip()]
    return lines, pos


def last_line(text):
    """The last non-blank line of a subprocess's stderr -- the part a person
    can act on ("sox not installed", "unknown name"), without the rest."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def play_earcon(name, device=None):
    """Returns (played, detail).

    crt-earcon.sh runs under `set -euo pipefail` and ends on aplay, so its
    exit status is a real answer to "did a tone come out of that device" --
    it is 1 for a missing sox, 1 for an ALSA device that will not open, 2 for
    an unknown earcon name. This threw all of that at /dev/null and returned
    nothing, which is the same defect f187a45 fixed in the sibling tool
    (crt-earcon-loopback-test.py, where a tone that never played and a tone
    the mic could not hear produced identical output).

    It matters more here, because here the verdict is rendered by a HUMAN:
    the round asked "did you hear it, and where" about a tone that had
    provably never sounded, and an honest "nowhere" then reads as broken
    routing. That is a wrong conclusion about the hardware, arrived at
    carefully -- the worst kind for a tool whose whole purpose is
    re-verifying routing without a hands-on session."""
    cmd = [EARCON_BIN, name]
    if device:
        cmd += ["--device", device]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                              stderr=subprocess.PIPE, text=True)
    except OSError as exc:                      # crt-earcon.sh missing/not +x
        return False, str(exc)
    if proc.returncode == 0:
        return True, ""
    return False, last_line(proc.stderr) or "exit %d" % proc.returncode


def record_routing(device, played, reported, detail, path=None):
    """Append one device-routing verdict. Returns True if it really landed.

    The round printed "-> logged: intended=tv, reported=nowhere" and logged
    nothing anywhere -- the whole session evaporated with the tmux scrollback,
    though this script's own header says the point is re-verifying routing
    "any time the hardware changes without a hands-on SSH session". A verdict
    nobody can read tomorrow is not a re-verification.

    JSONL, appended, one line per device, next to the other things this
    console writes down about itself."""
    path = os.path.expanduser(path or ROUTING_LOG)
    row = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "intended": device,
        "played": played,
        "reported": reported,
        "detail": detail,
    }
    try:
        parent = os.path.dirname(path)
        if parent:                      # a bare filename has none, and
            os.makedirs(parent, exist_ok=True)   # makedirs("") raises
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")
    except OSError as exc:
        # Say so. Claiming "logged" while failing to log is the defect this
        # function was written to fix, one level up.
        print("%s[!] could not write %s -- %s%s" % (DIM + WHITE, path, exc, RESET))
        return False
    return True


class Tailer:
    """Runs in a background thread for the ENTIRE game session, not just
    during a nominal 'round' -- the original per-round-only tailer went
    dead the instant a blocking input() prompt ran between rounds, so
    anything said in that gap (or right at a round boundary, given
    VAD-trail + remote-whisper round-trip latency) was silently dropped.
    This starts the moment the game launches and never stops until exit,
    so timing relative to prompts/rounds no longer matters."""

    def __init__(self, target):
        self.target = target
        self.seen = {}
        self._stop = False
        try:
            self.pos = os.path.getsize(os.path.expanduser(STT_LOG))
        except OSError:
            self.pos = 0

    def run(self):
        # Guarded, because this thread going quiet is invisible: the game
        # keeps prompting, the round still "ends", offer_to_save() still says
        # "Nothing worth saving", and the person is still saying the word into
        # a mic nothing is reading. An iteration that raises now says so on
        # this screen and on window 1, and the next one carries on -- which is
        # the whole reason crt_loop_guard.py exists. echo=True: unlike the four
        # background windows, someone is looking at this pane.
        guard = loop_guard.LoopGuard("calibration-game")

        def loop():
            while not self._stop:
                with guard:
                    lines, self.pos = tail_new_lines(os.path.expanduser(STT_LOG), self.pos)
                    for line in lines:
                        for word in line.lower().split():
                            word = "".join(c for c in word if c.isalnum())
                            if len(word) < 3:
                                continue
                            ratio = difflib.SequenceMatcher(None, word, self.target).ratio()
                            color = color_for_ratio(ratio)
                            pad = " " * (int(ratio * 12))
                            print("%s%s%-16s%s (%.0f%%)" % (pad, color, word, RESET, ratio * 100))
                            self.seen[word] = max(self.seen.get(word, 0.0), ratio)
                time.sleep(0.5)
        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop = True


def wake_round(tailer, target, seconds):
    print(POTATO)
    print("%s%s ROUND: say %r into the mic for the next %ds.%s"
          % (BRIGHT, CYAN, target, seconds, RESET))
    print("(listening continues between rounds too -- nothing is dropped)\n")
    time.sleep(seconds)
    print("\n%s-- round over (still listening) --%s" % (DIM + WHITE, RESET))
    return tailer.seen


SAVE_MIN_RATIO = 0.45   # below this a word is not a mishear, it is a word
SAVE_MAX_RATIO = 0.98   # at/above this STT already got it right
SAVE_LIMIT = 8          # how many the prompt actually offers


def save_candidates(seen, target, limit=SAVE_LIMIT):
    """The words this round is willing to save, best match first -- and the
    ONLY words it will accept, which is the point of returning them rather
    than re-deriving the rule at the prompt.

    Takes a snapshot (`dict(seen)`) because the caller's dict is the Tailer's
    live one: that thread keeps adding words for the entire session by
    design, including while a human reads this list and types, so iterating
    it directly races a `dictionary changed size during iteration` and means
    the set on screen is not the set the answer is checked against."""
    return sorted(
        ((w, r) for w, r in dict(seen).items()
         if w != target and SAVE_MIN_RATIO <= r < SAVE_MAX_RATIO),
        key=lambda kv: -kv[1],
    )[:limit]


def offer_to_save(seen, target):
    candidates = save_candidates(seen, target)
    if not candidates:
        print("Nothing worth saving -- either dead-on or too far off.")
        return
    offered = dict(candidates)
    print("\nCandidates to save as confirmed mishears of %r:" % target)
    for w, r in candidates:
        print("  %-16s %.0f%%" % (w, r * 100))
    choice = input("\nType a word to confirm-save it (or Enter to skip): ").strip().lower()
    if not choice:
        print("Skipped.")
        return
    # Only what was offered. Until 2026-07-25 this accepted any word the
    # tailer had EVER heard, which is every word said in the room since the
    # game launched -- so a typed "about" (18% similar, never on the list)
    # was written as a CONFIRMED mishear of the wake word, and confirmed is
    # the tier crt-stt-solo.py's gate acts on with no further review. The
    # console then woke on "what is this book about". The escape hatch for a
    # word that genuinely belongs is the one that was always there and is
    # reviewable: edit bin/stt-fixups.json, which is tracked in git.
    if choice not in offered:
        print("%r was not offered -- only the words listed above can be "
              "confirm-saved here." % choice)
        print("(Below %.0f%% it is a different word, not a mishear. To add it "
              "anyway, edit %s by hand.)" % (SAVE_MIN_RATIO * 100, FIXUPS_PATH))
        return
    save_fixup(choice, target, offered[choice], FIXUPS_PATH)
    print("Saved %r -> %r in %s" % (choice, target, FIXUPS_PATH))
    print("The wake gate picks this up on its next utterance -- "
          "crt-stt-solo.py re-reads this file when it changes.")


def save_fixup(fragment, target, similarity, path):
    """Record one confirmed mishear, through crt_fixups_store.update().

    The write is a temp file + os.replace for two reasons that predate this
    function's current shape: `open(path, "w")` truncates the real file
    first, so a crash or a full disk mid-dump destroys every hand-authored
    "confirmed" entry in a file that is tracked in git and holds human
    judgments this project cannot re-derive; and crt-stt-solo.py re-reads
    this file live while capture is running, so a reader can genuinely land
    inside the window where it is half-written.

    What changed 2026-07-25 is WHERE the existing entries come from. They
    used to be read here and written back a moment later, which meant the
    `stttrain` window's 600s merge tick could land in between and be
    silently erased by this save -- or erase it. The entry is now added
    inside the store's lock, to the file as it is at that instant."""
    def add(existing):
        existing[fragment] = {
            "intent": target,
            "confidence": "confirmed",
            "type": "calibration-game",
            "note": "confirmed live via crt-calibration-game.py, %.0f%% similarity"
                    % (similarity * 100),
        }
        return existing

    return fixups_store.update(path, add)


def earcon_round(path=None):
    print("\n%sEARCON ROUND%s -- confirming device routing by hand." % (BRIGHT + CYAN, RESET))
    print("(typed answers only -- can't use the mic to confirm the mic's own output path)\n")
    for device in ("tv", "handset"):
        input("Press Enter to play a tone on %r..." % device)
        played, detail = play_earcon("addressed", device)
        if not played:
            # Don't ask. A "nowhere" about a tone that never played is a
            # human being talked into a wrong finding about the hardware.
            print("%s[!] nothing played on %r -- %s%s" % (BRIGHT + MAGENTA, device, detail, RESET))
            print("    Not asking whether you heard it: there was no tone.")
            record_routing(device, False, None, detail, path)
            print("-> logged: intended=%s, played=no (%s)\n" % (device, detail))
            continue
        heard = input("Did you hear it, and where (tv/handset/nowhere)? ").strip().lower()
        if record_routing(device, True, heard or None, "", path):
            print("-> logged: intended=%s, reported=%s\n" % (device, heard or "no answer"))
        else:
            print("-> NOT logged: intended=%s, reported=%s\n" % (device, heard or "no answer"))


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "potato"
    seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    tailer = Tailer(target)
    tailer.run()
    try:
        seen = wake_round(tailer, target, seconds)
        offer_to_save(seen, target)
        if input("\nRun the earcon device-check round too? (y/N) ").strip().lower().startswith("y"):
            earcon_round()
    finally:
        tailer.stop()
    print("\ndone.")


if __name__ == "__main__":
    main()
