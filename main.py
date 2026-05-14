"""
JARVIS - Local AI Desktop Assistant
Entry point.

Hotkey: Ctrl+Space    → start listening
        Ctrl+Shift+X  → emergency stop
        Ctrl+C        → quit
"""

import threading
import logging
import signal
import sys

import keyboard

from config.settings import settings, setup_logging
from core.listener   import VoiceListener
from core.intent     import IntentEngine
from core.executor   import ActionExecutor
from core.tts        import Speaker
from core.safety     import SafetyGuard
from core.state      import AssistantState
from core.memory     import memory

# ── Logging (must be first) ───────────────────────────────────────────────────
setup_logging()
log = logging.getLogger("jarvis.main")


# ── Bootstrap ─────────────────────────────────────────────────────────────────
def build_pipeline():
    log.info("Initialising JARVIS modules…")
    state    = AssistantState()
    speaker  = Speaker()
    safety   = SafetyGuard(state)
    listener = VoiceListener()
    intent   = IntentEngine()
    executor = ActionExecutor(speaker, safety)
    return state, speaker, safety, listener, intent, executor


# ── Core turn ─────────────────────────────────────────────────────────────────
def run_turn(state, speaker, listener, intent, executor):
    if state.is_busy:
        log.warning("Already processing. Ignoring trigger.")
        return

    state.is_busy = True
    try:
        speaker.say("শুনছি…")

        text = listener.listen()
        if not text:
            speaker.say("বুঝতে পারিনি। আবার বলুন।")
            memory.log_command("", None, False, note="no speech detected")
            return

        log.info("Heard: %s", text)

        action = intent.parse(text)
        if not action:
            speaker.say(f"এটা আমি এখনো পারি না।")
            memory.log_command(text, None, False, note="no intent matched")
            return

        log.info("Intent: %s | Params: %s", action.name, action.params)

        confirm_text = action.describe()
        speaker.say(f"{confirm_text} — করবো?")
        print(f"\n[JARVIS] Action  : {confirm_text}")
        print(f"[JARVIS] Params  : {action.params}")
        print( "[JARVIS] Confirm : Y to go, N to cancel… ", end="", flush=True)

        confirmed = listener.listen_confirmation()
        if not confirmed:
            speaker.say("ঠিক আছে, বাদ দিলাম।")
            memory.log_command(text, action.name, False,
                               action.params, note="user cancelled")
            return

        speaker.say("করছি…")
        result = executor.run(action)

        if result.success:
            speaker.say(f"হয়ে গেছে। {result.message}")
        else:
            speaker.say(f"সমস্যা হয়েছে: {result.message}")
            log.error("Execution failed: %s", result.message)

    except Exception as exc:
        log.exception("Unexpected error in run_turn: %s", exc)
        speaker.say("একটা সমস্যা হয়েছে। লগ দেখুন।")
    finally:
        state.is_busy = False


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    state, speaker, safety, listener, intent, executor = build_pipeline()

    def emergency_stop():
        log.warning("EMERGENCY STOP triggered.")
        safety.engage_stop()
        speaker.say("থামছি।")
        sys.exit(0)

    def on_trigger():
        threading.Thread(
            target=run_turn,
            args=(state, speaker, listener, intent, executor),
            daemon=True,
        ).start()

    keyboard.add_hotkey("ctrl+shift+x", emergency_stop)
    keyboard.add_hotkey("ctrl+space",   on_trigger)

    def handle_sigint(sig, frame):
        log.info("Shutting down.")
        speaker.say("বন্ধ করছি।")
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sigint)

    speaker.say("JARVIS প্রস্তুত। Ctrl+Space চাপুন।")
    log.info("JARVIS ready | Ctrl+Space=listen | Ctrl+Shift+X=stop | Ctrl+C=quit")
    print("\n" + "═"*55)
    print("  JARVIS is running.")
    print("  Ctrl+Space       → give a command")
    print("  Ctrl+Shift+X     → emergency stop")
    print("  Ctrl+C           → quit")
    print("═"*55 + "\n")

    keyboard.wait()


if __name__ == "__main__":
    main()
