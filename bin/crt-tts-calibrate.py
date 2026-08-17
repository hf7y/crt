#!/usr/bin/env python3
# Interactive TTS calibration environment for the crt "secretary" voice.
# Plays short secretary-style phrases at different rate/pitch/voice/backend
# combos and lets you pick + save a profile to ~/.crt/tts.conf, which
# crt-tts.py (and everything downstream: announcements, spoken confirmations)
#   [rest: vault:crt/header-archaeology-20260817.md]
import os, sys, subprocess

# crt-tts.py has a hyphen in its name, can't `import` it -- shell out instead.
TTS_BIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crt-tts.py")

CONF = os.path.expanduser("~/.crt/tts.conf")

PHRASES = [
    "Hello, this is your secretary. How can I help?",
    "Your nightly build finished. Three items need attention, printed above.",
    "Reminder: the batch job runs again at one forty five.",
    "Say next page, or turn the scroll knob, to continue.",
]

# rate (wpm), pitch (0-99), label
ESPEAK_PRESETS = [
    (150, 45, "slow, low"),
    (165, 50, "default"),
    (185, 55, "brisk"),
    (150, 60, "slow, higher pitch"),
]


def speak(text, rate, pitch, voice="en-us", backend="espeak"):
    subprocess.run([sys.executable, TTS_BIN, text],
                    env={**os.environ, "CRT_TTS_BACKEND": backend,
                         "CRT_TTS_RATE": str(rate), "CRT_TTS_PITCH": str(pitch),
                         "CRT_TTS_VOICE": voice})


def save_profile(rate, pitch, voice, backend):
    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    with open(CONF, "w") as f:
        f.write("# crt TTS profile -- written by crt-tts-calibrate.py\n")
        f.write("CRT_TTS_BACKEND=%s\n" % backend)
        f.write("CRT_TTS_RATE=%s\n" % rate)
        f.write("CRT_TTS_PITCH=%s\n" % pitch)
        f.write("CRT_TTS_VOICE=%s\n" % voice)
    print("Saved profile to %s" % CONF)


def auto_default():
    # Sane default without audition: espeak-ng always installs cleanly, mid
    # rate/pitch. Re-run interactively once you can actually listen.
    save_profile(165, 50, "en-us", "espeak")
    print("Wrote a default (untuned) profile. Run without --auto later to "
          "actually pick by ear.")


def interactive():
    print("crt TTS calibration -- secretary voice tuning")
    print("Each option speaks all 4 sample phrases, then asks if you like it.\n")
    for rate, pitch, label in ESPEAK_PRESETS:
        print("--- %s (rate=%d pitch=%d) ---" % (label, rate, pitch))
        for p in PHRASES:
            speak(p, rate, pitch)
        ans = input("Keep this one? [y/N/q]: ").strip().lower()
        if ans == "q":
            print("Quit without saving.")
            return
        if ans == "y":
            save_profile(rate, pitch, "en-us", "espeak")
            return
    print("None picked. Run again, or edit %s by hand." % CONF)


if __name__ == "__main__":
    if "--auto" in sys.argv:
        auto_default()
    else:
        interactive()
