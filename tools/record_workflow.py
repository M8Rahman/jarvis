"""
tools/record_workflow.py
─────────────────────────
Records keyboard and mouse activity so you can see the exact steps
needed to navigate your ERP — then replicate them in erp_workflows.py.

Usage:
    python tools/record_workflow.py

Press  Ctrl+R  to start/stop recording.
Press  Ctrl+Q  to quit and save the log.

Output: logs/recorded_YYYYMMDD_HHMMSS.txt
"""

import datetime
import logging
import sys
import time

import keyboard
import pyautogui
from pynput import mouse as pynput_mouse
from pynput import keyboard as pynput_kb

LOG_PATH = None
events   = []
recording = False


def _ts():
    return datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]


# ── Mouse listener ────────────────────────────────────────────────────────────
def on_click(x, y, button, pressed):
    if recording and pressed:
        events.append(f"[{_ts()}] CLICK ({x}, {y}) {button}")
        print(f"  🖱  click ({x}, {y})")


def on_scroll(x, y, dx, dy):
    if recording:
        events.append(f"[{_ts()}] SCROLL ({x}, {y}) dy={dy}")


# ── Keyboard listener ─────────────────────────────────────────────────────────
def on_key_press(key):
    if recording:
        try:
            events.append(f"[{_ts()}] KEY_PRESS {key.char}")
        except AttributeError:
            events.append(f"[{_ts()}] KEY_PRESS {key}")


# ── Control ───────────────────────────────────────────────────────────────────
def toggle_recording():
    global recording
    recording = not recording
    state = "▶  RECORDING" if recording else "⏸  PAUSED"
    print(f"\n{state}\n")


def quit_and_save():
    global recording
    recording = False
    ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"logs/recorded_{ts}.txt"
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(events))
    print(f"\n✅ Saved {len(events)} events to {path}")
    print("\nUse this to replicate the steps in workflows/erp_workflows.py\n")
    sys.exit(0)


def main():
    print("═"*50)
    print("  JARVIS Workflow Recorder")
    print("  Ctrl+R  → start / pause recording")
    print("  Ctrl+Q  → save and quit")
    print("═"*50)

    keyboard.add_hotkey("ctrl+r", toggle_recording)
    keyboard.add_hotkey("ctrl+q", quit_and_save)

    m_listener = pynput_mouse.Listener(on_click=on_click, on_scroll=on_scroll)
    k_listener = pynput_kb.Listener(on_press=on_key_press)

    m_listener.start()
    k_listener.start()

    keyboard.wait()


if __name__ == "__main__":
    main()
