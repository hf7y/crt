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
#               the hardware changes without a hands-on SSH session.
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
import time

BIN_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(BIN_DIR)

_wp_spec = importlib.util.spec_from_file_location("crt_wake_pool", os.path.join(BIN_DIR, "crt-wake-pool.py"))
wake_pool = importlib.util.module_from_spec(_wp_spec)
_wp_spec.loader.exec_module(wake_pool)

STT_LOG = os.path.expanduser(os.environ.get("CRT_STT_LOG", "~/.crt/stt.log"))
FIXUPS_PATH = os.environ.get("CRT_STT_FIXUPS", os.path.join(BIN_DIR, "stt-fixups.json"))
EARCON_BIN = os.path.join(BIN_DIR, "crt-earcon.sh")

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
    tolerant same as every other log reader in this project."""
    try:
        with open(path) as f:
            f.seek(from_pos)
            chunk = f.read()
            pos = f.tell()
    except OSError:
        return [], from_pos
    lines = [ln.split("  ", 1)[-1] for ln in chunk.splitlines() if ln.strip()]
    return lines, pos


def play_earcon(name, device=None):
    cmd = [EARCON_BIN, name]
    if device:
        cmd += ["--device", device]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wake_round(target, seconds):
    print(POTATO)
    print("%s%s ROUND: say %r into the mic for the next %ds.%s"
          % (BRIGHT, CYAN, target, seconds, RESET))
    print("Each recognized word splashes below, scored against %r.\n" % target)

    try:
        pos = os.path.getsize(os.path.expanduser(STT_LOG))
    except OSError:
        pos = 0
    seen = {}
    deadline = time.time() + seconds
    while time.time() < deadline:
        lines, pos = tail_new_lines(os.path.expanduser(STT_LOG), pos)
        for line in lines:
            for word in line.lower().split():
                word = "".join(c for c in word if c.isalnum())
                if len(word) < 3:
                    continue
                ratio = difflib.SequenceMatcher(None, word, target).ratio()
                color = color_for_ratio(ratio)
                pad = " " * (int(ratio * 12))
                print("%s%s%-16s%s (%.0f%%)" % (pad, color, word, RESET, ratio * 100))
                seen[word] = max(seen.get(word, 0.0), ratio)
        time.sleep(0.5)

    print("\n%s-- round over --%s" % (DIM + WHITE, RESET))
    return seen


def offer_to_save(seen, target):
    candidates = sorted(
        ((w, r) for w, r in seen.items() if w != target and 0.45 <= r < 0.98),
        key=lambda kv: -kv[1],
    )
    if not candidates:
        print("Nothing worth saving -- either dead-on or too far off.")
        return
    print("\nCandidates to save as confirmed mishears of %r:" % target)
    for w, r in candidates[:8]:
        print("  %-16s %.0f%%" % (w, r * 100))
    choice = input("\nType a word to confirm-save it (or Enter to skip): ").strip().lower()
    if not choice or choice not in seen:
        print("Skipped.")
        return
    try:
        with open(FIXUPS_PATH) as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    data[choice] = {
        "intent": target,
        "confidence": "confirmed",
        "type": "calibration-game",
        "note": "confirmed live via crt-calibration-game.py, %.0f%% similarity"
                % (seen[choice] * 100),
    }
    with open(FIXUPS_PATH, "w") as f:
        json.dump(data, f, indent=4, sort_keys=True)
        f.write("\n")
    print("Saved %r -> %r in %s" % (choice, target, FIXUPS_PATH))


def earcon_round():
    print("\n%sEARCON ROUND%s -- confirming device routing by hand." % (BRIGHT + CYAN, RESET))
    print("(typed answers only -- can't use the mic to confirm the mic's own output path)\n")
    for device in ("tv", "handset"):
        input("Press Enter to play a tone on %r..." % device)
        play_earcon("addressed", device)
        heard = input("Did you hear it, and where (tv/handset/nowhere)? ").strip().lower()
        print("-> logged: intended=%s, reported=%s\n" % (device, heard or "no answer"))


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "potato"
    seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    seen = wake_round(target, seconds)
    offer_to_save(seen, target)
    if input("\nRun the earcon device-check round too? (y/N) ").strip().lower().startswith("y"):
        earcon_round()
    print("\ndone.")


if __name__ == "__main__":
    main()
