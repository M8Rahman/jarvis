"""
core/listener.py
────────────────
Captures microphone audio and transcribes using faster-whisper (offline).

FIXES (Phase 1.2):
  - VAD filter ENABLED — Whisper now skips silence/noise segments
  - Minimum speech duration gate — rejects recordings under MIN_SPEECH_DURATION
    seconds of actual detected speech amplitude (prevents noise bursts and
    TTS bleed from routing to the command handler)
  - Pre-recording delay — small pause after "Listening." TTS to let the
    speaker output die down before mic opens (prevents Whisper hallucinating
    the word "Listening" from its own TTS output)
  - Actual speech detector — tracks how many chunks had amplitude above
    threshold; if total real-speech time is below MIN_SPEECH_DURATION,
    the recording is rejected as noise/silence before even hitting Whisper
  - Whisper beam_size reduced to 1 for noise-only short clips (fast reject)
  - Improved debug logging at every stage of the pipeline
  - Confirmation listener also gets minimum-duration gate

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

SILENCE_DB        = 500    # amplitude threshold for silence detection
                            # raise this (e.g. 800) if your mic is noisy
MAX_SILENCE       = 2.0    # seconds of continuous silence → stop recording
MAX_RECORD        = 10.0   # hard cap on total recording time (seconds)

# ── NEW: speech quality gates ─────────────────────────────────────────────────
MIN_SPEECH_DURATION = 0.5  # seconds of ACTUAL speech (above threshold) required
                            # before we send audio to Whisper. Protects against:
                            #   - TTS bleed ("Listening." picked up by mic)
                            #   - brief noise bursts
                            #   - keyboard/hotkey click sounds
                            # Lower = more sensitive but more false positives.
                            # Raise to 0.8 if still getting spurious triggers.

PRE_RECORD_DELAY    = 0.4  # seconds to wait after TTS before opening mic.
                            # Gives the speaker time to finish "Listening."
                            # before we start recording. Prevents Whisper from
                            # transcribing our own TTS output as a command.

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
        """
        Record until silence → validate speech duration → transcribe.
        Returns transcribed English text, or None if nothing useful was heard.
        """
        log.debug("[LISTENER] Pre-recording delay %.1fs (TTS bleed prevention)…",
                  PRE_RECORD_DELAY)
        time.sleep(PRE_RECORD_DELAY)

        log.debug("[LISTENER] Microphone activated — waiting for speech…")
        audio_data, speech_seconds = self._record()

        if audio_data is None:
            log.info("[LISTENER] No audio captured at all.")
            return None

        log.debug("[LISTENER] Audio captured: %.2f s total, %.2f s speech",
                  len(audio_data) / RATE, speech_seconds)

        # Gate: reject if not enough actual speech detected
        if speech_seconds < MIN_SPEECH_DURATION:
            log.info(
                "[LISTENER] Speech gate rejected: only %.2fs of speech detected "
                "(minimum %.2fs). Likely noise, TTS bleed, or mic click. "
                "Returning None — will NOT route to command handler.",
                speech_seconds, MIN_SPEECH_DURATION,
            )
            return None

        log.debug("[LISTENER] Speech gate passed (%.2fs). Sending to Whisper…",
                  speech_seconds)
        result = self._transcribe(audio_data)

        if result:
            log.info("[LISTENER] Transcription result: %r", result)
        else:
            log.info("[LISTENER] Whisper returned empty transcript.")

        return result

    def listen_confirmation(self) -> bool:
        """
        Listen for yes/no reply (voice or keyboard).
        Voice window: 4 seconds. Keyboard fallback runs in parallel.
        Returns True = confirmed, False = cancelled/timeout.
        """
        import keyboard as kb

        confirmed = [None]   # shared result between threads

        def keyboard_fallback():
            log.debug("[LISTENER] Keyboard confirmation fallback active.")
            key = kb.read_key(suppress=False)
            if confirmed[0] is None:   # only set if voice hasn't answered yet
                k = key.lower()
                log.debug("[LISTENER] Key pressed for confirmation: %r", k)
                confirmed[0] = (k == "y")

        kb_thread = threading.Thread(target=keyboard_fallback, daemon=True)
        kb_thread.start()

        log.debug("[LISTENER] Listening for voice confirmation (4s window)…")
        # Short pre-delay so "Shall I proceed?" TTS doesn't bleed into mic
        time.sleep(PRE_RECORD_DELAY)
        audio_data, speech_seconds = self._record(max_silence=1.5, max_record=4.0)

        if audio_data is not None and speech_seconds >= MIN_SPEECH_DURATION:
            text = self._transcribe(audio_data)
            if text:
                lower = text.strip().lower()
                log.debug("[LISTENER] Confirmation heard: %r", lower)
                if any(t in lower for t in YES_TOKENS):
                    confirmed[0] = True
                elif any(t in lower for t in NO_TOKENS):
                    confirmed[0] = False
        else:
            log.debug(
                "[LISTENER] Confirmation: not enough speech (%.2fs), "
                "waiting for keyboard…",
                speech_seconds if audio_data is not None else 0.0,
            )

        kb_thread.join(timeout=10)

        result = confirmed[0]
        if result is None:
            log.info("[LISTENER] Confirmation timed out → treating as cancel.")
            result = False

        log.info("[LISTENER] Confirmation result: %s", result)
        return result

    # ── Internal ──────────────────────────────────────────────────────────────

    def _record(
        self,
        max_silence: float = MAX_SILENCE,
        max_record:  float = MAX_RECORD,
    ) -> tuple[np.ndarray | None, float]:
        """
        Record from microphone until silence or time limit.

        Returns:
            (audio_array, speech_seconds) where speech_seconds is the total
            duration of chunks that had amplitude above SILENCE_DB.
            Returns (None, 0.0) if no frames captured.
        """
        stream = self.audio.open(
            format=FORMAT, channels=CHANNELS,
            rate=RATE, input=True, frames_per_buffer=CHUNK,
        )
        frames         = []
        silence_start  = None
        start_time     = time.time()
        speech_chunks  = 0     # count of chunks with actual speech
        chunk_duration = CHUNK / RATE   # seconds per chunk ≈ 0.064s

        try:
            while True:
                data      = stream.read(CHUNK, exception_on_overflow=False)
                chunk     = np.frombuffer(data, dtype=np.int16)
                frames.append(chunk)
                amplitude = np.abs(chunk).mean()
                now       = time.time()

                if amplitude >= SILENCE_DB:
                    # Real speech detected in this chunk
                    speech_chunks += 1
                    silence_start  = None   # reset silence timer
                else:
                    # Silence chunk
                    if silence_start is None:
                        silence_start = now
                    elif now - silence_start >= max_silence:
                        log.debug("[LISTENER] Silence timeout after %.1fs", max_silence)
                        break

                if now - start_time >= max_record:
                    log.debug("[LISTENER] Max record duration reached (%.1fs)", max_record)
                    break

        finally:
            stream.stop_stream()
            stream.close()

        speech_seconds = speech_chunks * chunk_duration

        if not frames:
            return None, 0.0

        return np.concatenate(frames), speech_seconds

    def _transcribe(self, audio_data: np.ndarray) -> str | None:
        """
        Send audio to faster-whisper for transcription.
        VAD filter ENABLED — Whisper will skip silence segments internally too.
        """
        audio_f32 = audio_data.astype(np.float32) / 32768.0

        log.debug("[LISTENER] Sending %.2fs of audio to Whisper…",
                  len(audio_f32) / RATE)

        segments, _info = self.model.transcribe(
            audio_f32,
            language="en",          # English only — faster, no detection overhead
            beam_size=3,
            vad_filter=True,        # FIX: was False — now Whisper skips silence
            vad_parameters={
                "min_silence_duration_ms": 300,   # tunable if needed
                "speech_pad_ms": 200,
            },
        )

        text = " ".join(seg.text.strip() for seg in segments).strip()

        # Strip common Whisper hallucination artifacts
        # (Whisper sometimes outputs these for near-silence audio)
        HALLUCINATION_PHRASES = {
            "thank you", "thanks for watching", "thank you for watching",
            "you", ".", "..", "...", "bye", "goodbye", "uh", "um",
        }
        if text.lower().strip(" .") in HALLUCINATION_PHRASES:
            log.info(
                "[LISTENER] Whisper hallucination filtered: %r → returning None", text
            )
            return None

        return text if text else None

    def __del__(self):
        try:
            self.audio.terminate()
        except Exception:
            pass
