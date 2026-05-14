"""
core/tts.py
───────────
Offline Text-to-Speech using pyttsx3.

pyttsx3 uses the Windows built-in SAPI5 engine — zero internet, zero extra
download, runs on any Windows machine out of the box.

Bangla TTS note:
  Windows SAPI5 does not have a native Bangla voice. For now, JARVIS will
  speak the English portions correctly and attempt Bangla phonetically.
  
  Future upgrade path (Phase 3+):
    - Coqui TTS with a fine-tuned Bangla model (requires 16 GB+ RAM)
    - OR: keep responses mostly in English when TTS is on
"""

import logging
import pyttsx3

from config.settings import settings

log = logging.getLogger("jarvis.tts")


class Speaker:

    def __init__(self):
        self._engine = pyttsx3.init()
        self._configure()
        log.info("TTS engine ready.")

    def _configure(self):
        """Apply settings from config."""
        rate   = settings.get("tts_rate", 165)      # words per minute
        volume = settings.get("tts_volume", 0.9)    # 0.0 – 1.0

        self._engine.setProperty("rate",   rate)
        self._engine.setProperty("volume", volume)

        # Try to use a clearer voice if multiple are installed
        voices = self._engine.getProperty("voices")
        preferred = settings.get("tts_voice_name", "").lower()
        if preferred:
            for v in voices:
                if preferred in v.name.lower():
                    self._engine.setProperty("voice", v.id)
                    log.info("TTS voice set to: %s", v.name)
                    break

    def say(self, text: str):
        """Speak text aloud. Blocks until speech is complete."""
        log.debug("TTS: %s", text)
        try:
            self._engine.say(text)
            self._engine.runAndWait()
        except RuntimeError as exc:
            # Engine already running (shouldn't happen but guard anyway)
            log.warning("TTS RuntimeError: %s", exc)
