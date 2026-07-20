#!/usr/bin/env python3
# Streaming (LocalAgreement) STT engine -- Approach F prototype from
# AUDIO-DEBUG.md. NEW, OPT-IN, does not touch crt-stt-solo.py's working batch
# pipeline. NOT hardware-verified -- written on the dev box (no VM/handset).
#
# WHY: crt-stt-solo.py (and stt-feed.sh) both transcribe once, after the whole
# utterance has ended (VAD trail). That's simple and accurate but feels dead --
# nothing happens on screen until you stop talking. Browser/streaming ASR
# instead emits partial words *while you're still speaking* and revises them
# as more audio arrives. Whisper isn't natively streaming, but re-decoding a
# growing buffer every ~0.5s and only committing a word once two consecutive
# decodes agree on it (the "LocalAgreement-2" trick from whisper_streaming)
# approximates it without swapping out the model.
#
# COST WARNING: this re-decodes the ENTIRE utterance-so-far on every tick, so
# a 6s utterance with a 0.5s tick does ~12 decodes instead of crt-stt-solo.py's
# one. On a CPU-capped VirtualBox guest this may be too slow to feel live --
# that's an open question this prototype exists to let a human answer, not
# something claimed solved here. Point CRT_WHISPER_SERVER at
# bin/dexter-whisper-server.py (native-host faster-whisper) to sidestep the
# guest's CPU cap entirely; that is the expected way to make this usable.
#
# Reuses the same VAD/capture shape, hallucination filter, and CRT_STT_LOG /
# sink conventions as crt-stt-solo.py so it's a drop-in alternative, not a
# parallel universe. Does NOT reuse crt-stt-solo.py's ring/ctl-file/HUD
# machinery -- kept minimal on purpose for a first prototype.
#
#   bin/crt-stt-stream.py                                  # stdout, local whisper.cpp
#   CRT_WHISPER_SERVER=http://192.168.0.22:8991/transcribe bin/crt-stt-stream.py
#   CRT_STT_SINK=claude bin/crt-stt-stream.py               # types into tmux, like solo
#
# Tunables (env), on top of the ones shared with crt-stt-solo.py
# (CRT_AUDIO_DEV, CRT_VAD_THRESHOLD, CRT_WHISPER_BIN/MODEL, CRT_WHISPER_SERVER):
#   CRT_STREAM_INTERVAL   seconds between re-decodes while speech is ongoing
#                         (default 0.7 -- shorter feels livelier, costs more CPU)
#   CRT_STREAM_AGREE      consecutive matching decodes required to commit a
#                         word (default 2, the LocalAgreement-2 baseline)
#   CRT_STREAM_MIN_DECODE minimum buffered speech (s) before the first partial
#                         decode fires -- avoids wasting a decode on 0.3s of
#                         audio that's almost certainly garbage (default 1.0)
import sys, os, array, time, wave, tempfile, subprocess, datetime, urllib.request
from collections import deque

SINK    = os.environ.get("CRT_STT_SINK", "stdout")
SESSION = os.environ.get("CRT_TMUX_SESSION", "claude")
PANE    = os.environ.get("CRT_TMUX_PANE", "0")

RATE   = 16000
CHUNK  = int(RATE * 0.1)
NBYTES = CHUNK * 2
FULL   = 32768.0

DEV    = os.environ.get("CRT_AUDIO_DEV", "plughw:0,0")
WBIN   = os.environ.get("CRT_WHISPER_BIN",   os.path.expanduser("~/whisper.cpp/build/bin/whisper-cli"))
MODEL  = os.environ.get("CRT_WHISPER_MODEL", os.path.expanduser("~/whisper.cpp/models/ggml-base.en.bin"))
THRESH = float(os.environ.get("CRT_VAD_THRESHOLD", "1.0")) / 100.0
START  = int(os.environ.get("CRT_VAD_START_CHUNKS", "2"))
TRAIL  = float(os.environ.get("CRT_VAD_TRAIL", "0.8"))
MAXUTT = float(os.environ.get("CRT_VAD_MAX", "20"))
MINUTT = float(os.environ.get("CRT_VAD_MIN", "0.4"))
PREROLL= int(os.environ.get("CRT_VAD_PREROLL", "3"))
NORM   = os.environ.get("CRT_NORMALIZE", "1") != "0"
HP      = os.environ.get("CRT_HIGHPASS", "0")
NR_PROF = os.environ.get("CRT_NOISERED_PROF", "")
NR_AMT  = float(os.environ.get("CRT_NOISERED_AMT", "0.21"))

STREAM_INTERVAL   = float(os.environ.get("CRT_STREAM_INTERVAL", "0.7"))
STREAM_AGREE      = int(os.environ.get("CRT_STREAM_AGREE", "2"))
STREAM_MIN_DECODE = float(os.environ.get("CRT_STREAM_MIN_DECODE", "1.0"))

STT_LOG = os.environ.get("CRT_STT_LOG", os.path.expanduser("~/.crt/stt.log"))
STT_DEBUG_PERSIST = os.environ.get("CRT_STT_DEBUG_PERSIST", "0") != "0"

WHISPER_SERVER = os.environ.get("CRT_WHISPER_SERVER", "")
WHISPER_SERVER_TIMEOUT = float(os.environ.get("CRT_WHISPER_SERVER_TIMEOUT", "8"))

CHUNK_DUR = CHUNK / RATE

CONTROL = {
    "enter": "Enter", "submit": "Enter", "send": "Enter", "return": "Enter",
    "go": "Enter", "proceed": "Enter", "yes": "Enter", "yeah": "Enter",
    "yep": "Enter", "confirm": "Enter", "accept": "Enter", "okay": "Enter",
    "ok": "Enter",
    "no": "Escape", "nope": "Escape", "cancel": "Escape", "escape": "Escape",
    "abort": "Escape", "dismiss": "Escape", "nevermind": "Escape",
    "up": "Up", "previous": "Up", "back": "Up",
    "down": "Down", "next": "Down",
    "clear": "C-u", "scratch": "C-u", "backspace": "C-u",
}

HALLU = set("you thankyou thanks thankyouforwatching bye music musicplaying "
            "cricketschirping silence blankaudio sound soundeffects applause "
            "inaudible foreignspeech speaking".split())


def read_exact(f, n):
    b = bytearray()
    while len(b) < n:
        c = f.read(n - len(b))
        if not c:
            break
        b += c
    return bytes(b)


def send_to_claude(text, key):
    target = "%s:%s" % (SESSION, PANE)
    if " " not in text and key in CONTROL:
        subprocess.run(["tmux", "send-keys", "-t", target, CONTROL[key]])
        return
    subprocess.run(["tmux", "send-keys", "-t", target, "-l", text])
    subprocess.run(["tmux", "send-keys", "-t", target, "Enter"])


def transcribe_remote(wav_path):
    import json
    try:
        with open(wav_path, "rb") as f:
            data = f.read()
        req = urllib.request.Request(WHISPER_SERVER, data=data,
                                      headers={"Content-Type": "audio/wav"})
        with urllib.request.urlopen(req, timeout=WHISPER_SERVER_TIMEOUT) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        return result.get("text", "")
    except Exception:
        return ""


def transcribe(frames):
    """Decode a raw PCM buffer to text. Same filter chain as crt-stt-solo.py
    (highpass -> noisered -> normalize) so streaming/batch stay comparable."""
    raw = norm = None
    try:
        fd, raw = tempfile.mkstemp(suffix=".wav"); os.close(fd)
        with wave.open(raw, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
            w.writeframes(frames)
        feed = raw
        effects = []
        if HP != "0":
            effects += ["highpass", HP]
        if NR_PROF and os.path.exists(NR_PROF):
            effects += ["noisered", NR_PROF, "%.3f" % NR_AMT]
        if NORM:
            effects += ["gain", "-n", "-1"]
        if effects:
            norm = raw[:-4] + "_f.wav"
            if subprocess.run(["sox", raw, norm] + effects,
                              stderr=subprocess.DEVNULL).returncode == 0:
                feed = norm
        if WHISPER_SERVER:
            return transcribe_remote(feed)
        out = subprocess.run([WBIN, "-m", MODEL, "-f", feed, "-nt", "-np"],
                             capture_output=True, text=True).stdout
        return " ".join(out.split())
    except Exception:
        return ""
    finally:
        for p in (raw, norm):
            if p:
                try: os.unlink(p)
                except OSError: pass


def local_agreement_commit(committed_words, prev_words, new_words, need_agree):
    """Core of Approach F. `committed_words` is what's already been emitted
    (frozen, never revised again). `prev_words`/`new_words` are the last two
    decodes of the *whole* buffer-so-far (both start from the same audio
    origin, so they're directly comparable word-for-word). Advance the commit
    point past the longest prefix, beyond what's already committed, that the
    last `need_agree` consecutive decodes agree on.

    need_agree=2 (the default/baseline) means: agree with just the immediately
    prior decode. This function is called every tick with a 2-decode window,
    so 'agreement' here is literally prev==new on the shared prefix; higher
    need_agree is left as a knob for a future version that keeps a longer
    history instead of just one previous hypothesis -- not implemented in this
    prototype (documented gap, not a silent shortcut)."""
    start = len(committed_words)
    i = start
    while i < len(prev_words) and i < len(new_words) and prev_words[i] == new_words[i]:
        i += 1
    newly_committed = new_words[start:i]
    return committed_words + newly_committed


def emit_final(text, committed_words):
    """Finalize an utterance: same hallucination filter + sinks + logging as
    crt-stt-solo.py's emit(), so downstream behavior (log, claude typing) is
    identical regardless of which engine produced it. `committed_words` is
    shown for context in debug persist mode only -- the sink always gets the
    authoritative final decode, not the partial commit trail, since the final
    full-buffer decode is strictly more accurate than any partial."""
    key = "".join(c for c in text.lower() if c.isalpha())
    if not text or len(key) < 2 or key in HALLU:
        return
    t = text.strip()
    if t and t[0] in "([*♪" and t[-1] in ")]*♪":
        return
    sys.stdout.write("\n")
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    try:
        os.makedirs(os.path.dirname(STT_LOG), exist_ok=True)
        with open(STT_LOG, "a") as f:
            f.write("%s  %s\n" % (ts, text))
    except OSError:
        pass
    if SINK == "claude":
        label = "(key %s)" % CONTROL[key] if (" " not in text and key in CONTROL) else "->"
        print("%s  %s %s" % (ts, label, text))
        send_to_claude(text, key)
    else:
        print("%s  %s" % (ts, text))


def main():
    if SINK == "claude":
        while subprocess.run(["tmux", "has-session", "-t", SESSION],
                             stderr=subprocess.DEVNULL).returncode != 0:
            time.sleep(1)
    proc = subprocess.Popen(
        ["arecord", "-D", DEV, "-f", "S16_LE", "-c", "1", "-r", str(RATE), "-t", "raw"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    print("[crt-stt-stream] LocalAgreement prototype on %s  model=%s  thr=%.1f%%  tick=%.1fs"
          % (DEV, os.path.basename(MODEL) if not WHISPER_SERVER else WHISPER_SERVER,
             THRESH * 100, STREAM_INTERVAL))
    print("(NOT hardware-verified -- CPU cost of re-decoding may be too slow on the guest)")
    print("-" * 40)

    pre = deque(maxlen=PREROLL)
    in_utt = False
    utt_peak = 0.0
    buf = bytearray()
    above = 0
    sil = 0.0
    last_decode_at = 0.0
    committed_words = []
    prev_words = []

    try:
        while True:
            data = read_exact(proc.stdout, NBYTES)
            if len(data) < NBYTES:
                break
            a = array.array('h'); a.frombytes(data)
            peak = (max(abs(x) for x in a) / FULL) if a else 0.0
            now = time.time()

            if not in_utt:
                pre.append(data)
                if peak >= THRESH:
                    above += 1
                    if above >= START:
                        in_utt = True
                        buf = bytearray(b"".join(pre)); pre.clear()
                        sil = 0.0
                        utt_peak = peak
                        committed_words = []
                        prev_words = []
                        last_decode_at = now
                else:
                    above = 0
            else:
                buf += data
                utt_peak = max(utt_peak, peak)
                sil = sil + CHUNK_DUR if peak < THRESH else 0.0
                dur = len(buf) / 2 / RATE

                # Partial re-decode tick: only once we have enough audio to be
                # worth a decode, and not on every single 100ms chunk.
                if (dur >= STREAM_MIN_DECODE and now - last_decode_at >= STREAM_INTERVAL
                        and dur < MAXUTT):
                    last_decode_at = now
                    new_words = transcribe(bytes(buf)).split()
                    committed_words = local_agreement_commit(
                        committed_words, prev_words, new_words, STREAM_AGREE)
                    prev_words = new_words
                    shown = " ".join(committed_words)
                    tail = " ".join(new_words[len(committed_words):])
                    sys.stdout.write("\r\033[K%s\033[2m%s\033[0m" % (
                        shown + (" " if shown and tail else ""), tail))
                    sys.stdout.flush()

                if sil >= TRAIL or dur >= MAXUTT:
                    in_utt = False; above = 0
                    if dur >= MINUTT:
                        final_text = transcribe(bytes(buf))
                        emit_final(final_text, committed_words)
                    else:
                        sys.stdout.write("\r\033[K")
                    buf = bytearray()
    except KeyboardInterrupt:
        pass
    finally:
        try: proc.terminate()
        except Exception: pass


if __name__ == "__main__":
    main()
