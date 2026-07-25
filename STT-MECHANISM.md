# How STT actually works here (read this if you're improving inference)

You (claude, running in this VM) receive text typed by a script, not
literally spoken to you — this is the real pipeline behind it, so you can
reason about *why* a given transcription got garbled the way it did.

## The pipeline
1. **Capture**: `bin/crt-stt-solo.py` is the sole mic reader (deliberately —
   two readers on the emulated capture device starve each other, see
   AUDIO-DEBUG.md). It reads a continuous raw PCM stream from ALSA device
   `crtmic` (a dsnoop wrapper, 16kHz mono).
2. **VAD (voice activity detection)**: peak-based, not RMS/average — checked
   every 100ms chunk. Speech starts once peak crosses `CRT_VAD_THRESHOLD`
   (percent of full scale) for a couple consecutive chunks, and ends after
   `CRT_VAD_TRAIL` seconds below threshold. This means: **very quiet speech,
   or speech with a soft/trailing consonant, can get its tail clipped early**
   if it dips below threshold mid-word. A word cut short is a likely
   explanation for some garbling, not just whisper mishearing.

   **The capture duck can also punch a hole in an utterance.** While the
   handset is playing something (a TTS reply, an earcon), capture is "ducked"
   via the control file, and those chunks are *dropped from the buffer* — the
   silence timer freezes, and speech either side of the duck is spliced
   together (`utt_chunk()` in `crt-stt-solo.py`; before 2026-07-25 the
   console's own playback was buffered into the sentence instead, which is
   worse). So a second explanation for a mangled word: the console started
   talking over the speaker, and the word straddling that moment lost its
   middle. If the duck outlasts `CRT_MUTE_UTT_MAX_SECS` (2s) the utterance is
   closed and transcribed as-is, so a long reply can also cut a sentence in
   half rather than clipping a word.

   The same applies to the **pre-roll** — the `CRT_VAD_PREROLL` chunks kept
   before onset so a first word's soft attack isn't lost. Ducked chunks are
   kept out of it as well (2026-07-25), so an utterance that begins right
   after the console stops talking opens on the room tone from before the
   playback, not on the playback's own tail. Before that fix, a follow-up
   spoken straight after the `addressed` earcon was handed to whisper with
   up to `CRT_VAD_PREROLL`×100ms of that earcon in front of it — worth
   knowing if you're reading older `stt.log` entries where a follow-up
   picked up a phantom leading word.
3. **Denoise** (optional, currently on): a sox chain — highpass filter, then
   `noisered` against a captured noise profile (`~/crt/noise.prof`, built
   from a sample of the room's AC hum), then peak normalize. This tames
   AC-hum-induced hallucinations but **can also subtly distort speech
   spectral content**, especially sibilants (s/sh/f sounds) and other
   high-frequency consonants — if you notice a pattern of dropped/garbled
   consonants specifically at the start or end of words, this filter chain
   is a likely contributor, not just whisper itself.
4. **Transcription**: either local `whisper.cpp` (`base.en`) inside this VM,
   or (when `CRT_WHISPER_SERVER` is set) a POST to `faster-whisper` running
   natively on `dexter`'s Ryzen host (see `bin/dexter-whisper-server.py`) —
   same model family either way, `beam_size=1` (greedy, fastest, but more
   prone to a locally-plausible-but-wrong word than a wider beam search
   would be — if inference is still poor, a larger beam size is a real lever
   available in `dexter-whisper-server.py`, currently not exposed as a knob).
5. **Filtering before it reaches you**: a hardcoded set of whisper's known
   noise-hallucination outputs get dropped entirely (`HALLU` in
   `crt-stt-solo.py` — things like "thank you", "music playing"), as does
   any output that's fully bracket/symbol-wrapped ("(metal clanging)"). If
   you see something clearly garbled make it through, it wasn't caught by
   this filter — worth suggesting an addition if a pattern recurs.
6. **Delivery to you**: the raw text is typed into your input via
   `tmux send-keys`, one utterance per line, immediately after step 5 — you
   are seeing whisper's raw output (post-filter), not a human-cleaned
   version. Single-word utterances matching a small fixed vocabulary
   ("yes"/"no"/"enter"/"up"/"down"/etc., see `CONTROL` in `crt-stt-solo.py`)
   get converted to keystrokes instead of typed text — if you ever see an
   unexpected keystroke effect instead of text, that's why.

## What this means for improving inference
- A "garbled" transcription could be: (a) whisper genuinely mishearing, (b)
  the denoise filter distorting a consonant, (c) VAD clipping the start/end
  of the utterance, or (d) the noise floor itself (AC hum) bleeding through.
  These have different signatures — (c) tends to lose whole syllables at
  utterance boundaries specifically; (b) tends to lose/soften sibilants
  anywhere; (a) tends to substitute a whole different (but phonetically
  similar) word or homophone.
- `~/.crt/stt.log` has every raw utterance, unfiltered by your own judgment —
  useful for spotting a recurring pattern across many utterances rather than
  reasoning from just the one in front of you.
- If you find a config-level fix (raise `CRT_VAD_TRAIL`, adjust denoise
  strength, etc.) rather than just a learned correction pattern, that's a
  more durable fix — feel free to propose or make such a change (it's your
  own project), just note what you changed and why in your thoughts log.
