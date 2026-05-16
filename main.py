"""
JARVIS - Local AI Desktop Assistant
Entry point.

Hotkeys (configurable in jarvis.yaml → listen_hotkey / stop_hotkey):
  Default listen : Ctrl+Alt
  Emergency stop : Ctrl+Shift+X
  Quit           : Ctrl+C in terminal

FIXES (Phase 1.2):
  - speaker.say_and_wait() used for "Listening." so mic opens AFTER
    TTS finishes speaking, not during it
  - Empty transcript now says "didn't hear" not "cannot handle"
  - Noise-only recordings (filtered by speech gate) return None from
    listener.listen() and are handled as "nothing heard"
  - import time added (was missing, caused NameError in prior version)
  - Debug logging added at every stage of the turn pipeline
"""

import threading
import logging
import signal
import sys
import time

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
        log.warning("[MAIN] Already processing. Ignoring trigger.")
        return

    state.is_busy = True
    try:
        log.debug("[MAIN] Hotkey triggered — starting listening turn.")

        # Use say_and_wait so the mic only opens AFTER "Listening." has
        # finished playing. This prevents Whisper from transcribing the
        # word "Listening" from our own speaker output.
        speaker.say_and_wait("Listening.")
        log.debug("[MAIN] TTS finished. Opening microphone now.")

        text = listener.listen()

        # ── Case 1: Nothing heard / only noise / TTS bleed filtered ──────────
        if not text:
            log.info("[MAIN] No valid speech detected. Prompting retry.")
            speaker.say("I didn't hear anything. Please press the hotkey and try again.")
            memory.log_command("", None, False, note="no speech detected / noise filtered")
            return

        log.info("[MAIN] Heard: %r", text)

        # ── Case 2: Intent matching ───────────────────────────────────────────
        log.debug("[MAIN] Routing to intent engine: %r", text)
        action = intent.parse(text)

        if not action:
            log.warning("[MAIN] No intent matched for: %r", text)
            speaker.say(f"I heard you say: {text}. But I cannot handle that command yet.")
            memory.log_command(text, None, False, note="no intent matched")
            return

        log.info("[MAIN] Intent matched: %s | Params: %s", action.name, action.params)

        # ── Case 3: Confirmation ──────────────────────────────────────────────
        confirm_text = action.describe()
        speaker.say_and_wait(f"{confirm_text}. Shall I proceed?")
        print(f"\n[JARVIS] Action  : {confirm_text}")
        print(f"[JARVIS] Params  : {action.params}")
        print( "[JARVIS] Confirm : Say YES or press Y to go, NO or N to cancel… ",
               end="", flush=True)

        log.debug("[MAIN] Waiting for confirmation…")
        confirmed = listener.listen_confirmation()

        if not confirmed:
            log.info("[MAIN] User cancelled action: %s", action.name)
            speaker.say("Cancelled.")
            memory.log_command(text, action.name, False,
                               action.params, note="user cancelled")
            return

        # ── Case 4: Execute ───────────────────────────────────────────────────
        log.info("[MAIN] Confirmed. Executing action: %s", action.name)
        speaker.say("Working on it.")
        result = executor.run(action)
        log.debug("[MAIN] Action result: success=%s msg=%r",
                  result.success, result.message)

        if result.success:
            speaker.say(f"Done. {result.message}")
        else:
            speaker.say(f"There was a problem: {result.message}")
            log.error("[MAIN] Execution failed: %s", result.message)

    except Exception as exc:
        log.exception("[MAIN] Unexpected error in run_turn: %s", exc)
        speaker.say("An unexpected error occurred. Please check the log.")
    finally:
        state.is_busy = False
        log.debug("[MAIN] Turn complete. Ready for next command.")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    # Read hotkeys from config — easy to override in jarvis.yaml
    listen_hotkey = settings.get("listen_hotkey", "ctrl+alt")
    stop_hotkey   = settings.get("stop_hotkey",   "ctrl+shift+x")

    state, speaker, safety, listener, intent, executor = build_pipeline()

    def emergency_stop():
        log.warning("[MAIN] EMERGENCY STOP triggered.")
        safety.engage_stop()
        speaker.say("Emergency stop. All actions halted.")
        time.sleep(1.5)
        sys.exit(0)

    def on_trigger():
        log.debug("[MAIN] Listen hotkey pressed: %s", listen_hotkey)
        threading.Thread(
            target=run_turn,
            args=(state, speaker, listener, intent, executor),
            daemon=True,
        ).start()

    keyboard.add_hotkey(stop_hotkey,   emergency_stop)
    keyboard.add_hotkey(listen_hotkey, on_trigger)

    def handle_sigint(sig, frame):
        log.info("[MAIN] Ctrl+C received. Shutting down.")
        speaker.say("Shutting down. Goodbye.")
        time.sleep(1.5)
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sigint)

    speaker.say(f"JARVIS is ready. Press {listen_hotkey} to give a command.")
    log.info("JARVIS ready | listen=%s | stop=%s | quit=Ctrl+C",
             listen_hotkey, stop_hotkey)

    print("\n" + "═"*55)
    print("  JARVIS is running.")
    print(f"  {listen_hotkey.upper():<20} → give a command")
    print(f"  {stop_hotkey.upper():<20} → emergency stop")
    print( "  Ctrl+C               → quit")
    print("═"*55)
    print()

    keyboard.wait()


if __name__ == "__main__":
    main()
