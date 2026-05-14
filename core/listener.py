"""
core/listener.py
────────────────
Captures microphone audio and transcribes it using faster-whisper (offline).

Model choice:
  "tiny"   →  ~150 MB RAM, fastest,  lower accuracy
  "base"   →  ~300 MB RAM, balanced  ← DEFAULT for 8 GB systems
  "small"  →  ~500 MB RAM, better Banglish accuracy
  "medium" →  ~1.5 GB RAM, best quality (use at 16 GB+)

Banglish handling:
  Whisper natively handles code-switched Bengali+English because it was
  trained on multilingual data. The 'base' model already handles Banglish
  reasonably well. Set WHISPER_MODEL="small" in config for better results.
"""

import logging
import tempfile
import wave
import time

import pyaudio                          # microphone input
import numpy as np
from faster_whisper import WhisperModel  # offline STT

from config.settings import settings

log = logging.getLogger("jarvis.listener")

# ── Constants ─────────────────────────────────────────────────────────────────
RATE        = 16_000   # Hz  (Whisper expects 16 kHz)
CHANNELS    = 1
CHUNK       = 1024
FORMAT      = pyaudio.paInt16
SILENCE_DB  = 500      # amplitude threshold to detect silence
MAX_SILENCE = 2.0      # seconds of silence before we stop recording
MAX_RECORD  = 10.0     # hard cap on recording length (seconds)

# Words / phrases that mean "yes / confirm"
YES_TOKENS  = {
    "yes", "y", "yeah", "yep", "confirm", "ok", "okay",
    "হ্যাঁ", "হ্যা", "han", "ha", "করো", "koro", "do it",
}
# Words / phrases that mean "no / cancel"
NO_TOKENS   = {
    "no", "n", "nope", "cancel", "stop", "বাদ", "না", "na",
}


class VoiceListener:
    """Records from mic, transcribes with Whisper (offline)."""

    def __init__(self):
        model_name = settings.get("whisper_model", "base")
        log.info("Loading Whisper model '%s' …", model_name)
        # device="cpu", compute_type="int8" → minimal RAM, acceptable speed
        self.model = WhisperModel(model_name, device="cpu", compute_type="int8")
        self.audio = pyaudio.PyAudio()
        log.info("Whisper model loaded.")

    # ── Public API ────────────────────────────────────────────────────────────

    def listen(self) -> str | None:
        """Record until silence, then return transcribed text (or None)."""
        audio_data = self._record()
        if audio_data is None:
            return None
        return self._transcribe(audio_data)

    def listen_confirmation(self) -> bool:
        """
        Listen for a short yes/no reply.
        Also accepts keyboard fallback: Y key → True, any other → False.
        Returns True if confirmed, False otherwise.
        """
        import keyboard as kb

        confirmed = [None]  # mutable container for thread result

        def keyboard_fallback():
            """Wait for Y/N keypress as fallback."""
            key = kb.read_key(suppress=False)
            if key.lower() == "y":
                confirmed[0] = True
            else:
                confirmed[0] = False

        import threading
        kb_thread = threading.Thread(target=keyboard_fallback, daemon=True)
        kb_thread.start()

        # Try voice first (3 second window)
        audio_data = self._record(max_silence=1.5, max_record=4.0)
        if audio_data is not None:
            text = self._transcribe(audio_data)
            if text:
                lower = text.strip().lower()
                if any(t in lower for t in YES_TOKENS):
                    confirmed[0] = True
                elif any(t in lower for t in NO_TOKENS):
                    confirmed[0] = False

        # Wait for keyboard thread if voice gave no answer
        kb_thread.join(timeout=5)

        result = confirmed[0]
        if result is None:
            result = False   # timeout → treat as cancel

        log.info("Confirmation result: %s", result)
        return result

    # ── Internal ──────────────────────────────────────────────────────────────

    def _record(
        self,
        max_silence: float = MAX_SILENCE,
        max_record: float  = MAX_RECORD,
    ) -> np.ndarray | None:
        """
        Record audio from mic.
        Stops when silence persists for `max_silence` seconds
        or `max_record` seconds total elapsed.
        Returns numpy int16 array or None on error.
        """
        stream = self.audio.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            frames_per_buffer=CHUNK,
        )

        frames        = []
        silence_start = None
        start_time    = time.time()
        log.debug("Recording started.")

        try:
            while True:
                data  = stream.read(CHUNK, exception_on_overflow=False)
                chunk = np.frombuffer(data, dtype=np.int16)
                frames.append(chunk)

                amplitude = np.abs(chunk).mean()
                now       = time.time()

                if amplitude < SILENCE_DB:
                    if silence_start is None:
                        silence_start = now
                    elif now - silence_start >= max_silence:
                        log.debug("Silence detected, stopping.")
                        break
                else:
                    silence_start = None   # reset silence timer on sound

                if now - start_time >= max_record:
                    log.debug("Max record time reached.")
                    break
        finally:
            stream.stop_stream()
            stream.close()

        if not frames:
            return None

        return np.concatenate(frames)

    def _transcribe(self, audio_data: np.ndarray) -> str | None:
        """Run Whisper on raw int16 numpy array, return text."""
        # Whisper expects float32 normalised to [-1, 1]
        audio_f32 = audio_data.astype(np.float32) / 32768.0

        segments, info = self.model.transcribe(
            audio_f32,
            language=None,       # auto-detect (handles Banglish)
            beam_size=3,         # lower = faster, slight accuracy trade-off
            vad_filter=True,     # skip silent segments automatically
        )

        text = " ".join(seg.text.strip() for seg in segments).strip()
        log.info("Transcribed [lang=%s]: %s", info.language, text)
        return text if text else None

    def __del__(self):
        try:
            self.audio.terminate()
        except Exception:
            pass
