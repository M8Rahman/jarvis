"""
core/tts.py
───────────
Offline Text-to-Speech using pyttsx3 (Windows SAPI5).

FIX: pyttsx3 threading bug — "run loop already started"
  Root cause: pyttsx3's engine is not thread-safe. When say() is called
  from a daemon thread while the engine is mid-runAndWait() (e.g. during
  shutdown or emergency stop), it raises RuntimeError.

  Solution: run the TTS engine in its own dedicated background thread with
  a queue. The main code calls speaker.say(text) which puts text in the
  queue and returns immediately. The TTS thread processes one item at a
  time. No concurrent runAndWait() calls ever happen.

English-only note:
  All spoken responses are now English only. Bengali text removed from
  spoken output since Windows SAPI5 has no Bengali voice and it was
  causing garbled speech.
"""

import logging
import queue
import threading

import pyttsx3

from config.settings import settings

log = logging.getLogger("jarvis.tts")


class Speaker:

    def __init__(self):
        self._queue:  queue.Queue = queue.Queue()
        self._thread: threading.Thread = threading.Thread(
            target=self._worker, daemon=True, name="tts-worker"
        )
        self._thread.start()
        log.info("TTS engine ready (dedicated thread).")

    def say(self, text: str):
        """
        Queue text for speaking. Returns immediately — non-blocking.
        The TTS worker thread speaks it in order.
        """
        log.debug("TTS queued: %s", text)
        self._queue.put(text)

    def say_and_wait(self, text: str):
        """
        Queue text AND block until it has been spoken.
        Use this when you need to wait for a response before proceeding.
        """
        done = threading.Event()
        self._queue.put((text, done))
        done.wait(timeout=15)

    def _worker(self):
        """Dedicated TTS thread. Owns the pyttsx3 engine exclusively."""
        engine = pyttsx3.init()

        # Apply settings
        engine.setProperty("rate",   settings.get("tts_rate",   165))
        engine.setProperty("volume", settings.get("tts_volume", 0.9))

        preferred = settings.get("tts_voice_name", "").lower()
        if preferred:
            for v in engine.getProperty("voices"):
                if preferred in v.name.lower():
                    engine.setProperty("voice", v.id)
                    log.info("TTS voice: %s", v.name)
                    break

        while True:
            item = self._queue.get()   # blocks until something is queued

            # Item is either a plain string or a (string, Event) tuple
            if isinstance(item, tuple):
                text, done_event = item
            else:
                text, done_event = item, None

            try:
                engine.say(text)
                engine.runAndWait()
            except Exception as exc:
                log.warning("TTS error: %s", exc)
            finally:
                if done_event:
                    done_event.set()

            self._queue.task_done()
