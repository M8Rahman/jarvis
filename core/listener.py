"""
core/listener.py
────────────────
Captures microphone audio and transcribes using faster-whisper (offline).

CHANGES:
  - language="en" hardcoded — English only, no auto-detect overhead
  - Faster response: language detection removed saves ~200ms per command
  - YES/NO tokens cleaned to English only (Bengali tokens removed)
  - Model still configurable via jarvis.yaml (tiny/base/small/medium)

Model RAM guide:
  tiny   ~150 MB  fastest, lower accuracy
  base   ~300 MB  good balance for 8 GB RAM  ← default
  small  ~500 MB  better accuracy
  medium ~1.5 GB  best, needs 16 GB+
"""

import logging
import time
import threading

import pyaudio
import numpy as np
from faster_whisper import WhisperModel

from config.settings import settings

log = logging.getLogger("jarvis.listener")

# ── Audio constants ───────────────────────────────────────────────────────────
RATE        = 16_000
CHANNELS    = 1
CHUNK       = 1024
FORMAT      = pyaudio.paInt16
SILENCE_DB  = 500     # amplitude threshold — raise if mic is noisy
MAX_SILENCE = 2.0     # seconds of silence → stop recording
MAX_RECORD  = 10.0    # hard cap (seconds)

# ── English-only confirmation tokens ─────────────────────────────────────────
YES_TOKENS = {
    "yes", "y", "yeah", "yep", "yup", "confirm", "ok", "okay",
    "go", "do it", "proceed", "correct", "sure", "affirmative",
}
NO_TOKENS = {
    "no", "n", "nope", "cancel", "stop", "abort", "negative",
    "don't", "dont", "skip",
}


class VoiceListener:

    def __init__(self):
        model_name = settings.get("whisper_model", "base")
        log.info("Loading Whisper model '%s' (English only)…", model_name)
        self.model = WhisperModel(model_name, device="cpu", compute_type="int8")
        self.audio = pyaudio.PyAudio()
        log.info("Whisper model loaded.")

    # ── Public API ────────────────────────────────────────────────────────────

    def listen(self) -> str | None:
        """Record until silence → transcribe → return English text."""
        audio_data = self._record()
        if audio_data is None:
            return None
        return self._transcribe(audio_data)

    def listen_confirmation(self) -> bool:
        """
        Listen for yes/no reply (voice or keyboard).
        Voice window: 4 seconds. Keyboard fallback runs in parallel.
        Returns True = confirmed, False = cancelled/timeout.
        """
        import keyboard as kb

        confirmed = [None]   # shared result between threads

        def keyboard_fallback():
            key = kb.read_key(suppress=False)
            if confirmed[0] is None:   # only set if voice hasn't answered yet
                confirmed[0] = key.lower() == "y"

        kb_thread = threading.Thread(target=keyboard_fallback, daemon=True)
        kb_thread.start()

        # Voice window
        audio_data = self._record(max_silence=1.5, max_record=4.0)
        if audio_data is not None:
            text = self._transcribe(audio_data)
            if text:
                lower = text.strip().lower()
                if any(t in lower for t in YES_TOKENS):
                    confirmed[0] = True
                elif any(t in lower for t in NO_TOKENS):
                    confirmed[0] = False

        kb_thread.join(timeout=10)

        result = confirmed[0]
        if result is None:
            result = False   # timeout → cancel

        log.info("Confirmation: %s", result)
        return result

    # ── Internal ──────────────────────────────────────────────────────────────

    def _record(
        self,
        max_silence: float = MAX_SILENCE,
        max_record:  float = MAX_RECORD,
    ) -> np.ndarray | None:
        stream = self.audio.open(
            format=FORMAT, channels=CHANNELS,
            rate=RATE, input=True, frames_per_buffer=CHUNK,
        )
        frames        = []
        silence_start = None
        start_time    = time.time()

        try:
            while True:
                data      = stream.read(CHUNK, exception_on_overflow=False)
                chunk     = np.frombuffer(data, dtype=np.int16)
                frames.append(chunk)
                amplitude = np.abs(chunk).mean()
                now       = time.time()

                if amplitude < SILENCE_DB:
                    if silence_start is None:
                        silence_start = now
                    elif now - silence_start >= max_silence:
                        break
                else:
                    silence_start = None

                if now - start_time >= max_record:
                    break
        finally:
            stream.stop_stream()
            stream.close()

        return np.concatenate(frames) if frames else None

    def _transcribe(self, audio_data: np.ndarray) -> str | None:
        audio_f32 = audio_data.astype(np.float32) / 32768.0
        segments, info = self.model.transcribe(
            audio_f32,
            language="en",      # English only — faster, no detection overhead
            beam_size=3,
            vad_filter=False,
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        log.info("Transcribed: %s", text)
        return text if text else None

    def __del__(self):
        try:
            self.audio.terminate()
        except Exception:
            pass
