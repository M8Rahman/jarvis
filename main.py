"""
JARVIS - Local AI Desktop Assistant
Entry point.

Hotkeys (configurable in jarvis.yaml → listen_hotkey / stop_hotkey):
  Default listen : Ctrl+Shift+A   (safe in VS Code and most apps)
  Emergency stop : Ctrl+Shift+X
  Quit           : Ctrl+C in terminal

WHY Ctrl+Shift+A?
  - Ctrl+Space    → VS Code autocomplete (conflicts)
  - Alt+Space     → Windows system menu (conflicts)
  - Ctrl+Shift+J  → VS Code "Join Lines" (conflicts)
  - Ctrl+Shift+A  → no default binding in VS Code or Windows ← chosen

All responses are English only (Windows SAPI5 has no Bengali voice).
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
        speaker.say("Listening.")

        text = listener.listen()
        if not text:
            speaker.say("Sorry, I did not catch that. Please try again.")
            memory.log_command("", None, False, note="no speech detected")
            return

        log.info("Heard: %s", text)

        action = intent.parse(text)
        if not action:
            speaker.say(f"I cannot handle that command yet: {text}")
            memory.log_command(text, None, False, note="no intent matched")
            return

        log.info("Intent: %s | Params: %s", action.name, action.params)

        confirm_text = action.describe()
        speaker.say(f"{confirm_text}. Shall I proceed?")
        print(f"\n[JARVIS] Action  : {confirm_text}")
        print(f"[JARVIS] Params  : {action.params}")
        print( "[JARVIS] Confirm : Say YES or press Y to go, NO or N to cancel… ",
               end="", flush=True)

        confirmed = listener.listen_confirmation()
        if not confirmed:
            speaker.say("Cancelled.")
            memory.log_command(text, action.name, False,
                               action.params, note="user cancelled")
            return

        speaker.say("Working on it.")
        result = executor.run(action)

        if result.success:
            speaker.say(f"Done. {result.message}")
        else:
            speaker.say(f"There was a problem: {result.message}")
            log.error("Execution failed: %s", result.message)

    except Exception as exc:
        log.exception("Unexpected error in run_turn: %s", exc)
        speaker.say("An unexpected error occurred. Please check the log.")
    finally:
        state.is_busy = False


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    # Read hotkeys from config — easy to override in jarvis.yaml
    listen_hotkey = settings.get("listen_hotkey", "ctrl+shift+a")
    stop_hotkey   = settings.get("stop_hotkey",   "ctrl+shift+x")

    state, speaker, safety, listener, intent, executor = build_pipeline()

    def emergency_stop():
        log.warning("EMERGENCY STOP triggered.")
        safety.engage_stop()
        speaker.say("Emergency stop. Shutting down.")
        # Give TTS a moment to finish speaking before exit
        import time; time.sleep(1.5)
        sys.exit(0)

    def on_trigger():
        threading.Thread(
            target=run_turn,
            args=(state, speaker, listener, intent, executor),
            daemon=True,
        ).start()

    keyboard.add_hotkey(stop_hotkey,   emergency_stop)
    keyboard.add_hotkey(listen_hotkey, on_trigger)

    def handle_sigint(sig, frame):
        log.info("Shutting down.")
        speaker.say("Shutting down. Goodbye.")
        import time; time.sleep(1.5)
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sigint)

    speaker.say(f"JARVIS is ready. Press {listen_hotkey} to give a command.")
    log.info("JARVIS ready | listen=%s | stop=%s | quit=Ctrl+C",
             listen_hotkey, stop_hotkey)

    print("\n" + "═"*55)
    print("  JARVIS is running.  (English commands only)")
    print(f"  {listen_hotkey.upper():<20} → give a command")
    print(f"  {stop_hotkey.upper():<20} → emergency stop")
    print( "  Ctrl+C               → quit")
    print("═"*55)
    print()

    keyboard.wait()


if __name__ == "__main__":
    main()
