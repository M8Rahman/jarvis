"""
workflows/erp_workflows.py
──────────────────────────
All ERP automation workflows live here.

Phase 1.3 changes:
  - All Bangla text removed. English only.

HOW TO CUSTOMIZE FOR YOUR ERP:
──────────────────────────────
1. Set `erp_window_title` in config/jarvis.yaml to match your ERP's title bar.
2. For each workflow, record what keys/clicks are needed manually first.
3. Replace the placeholder steps below with your real navigation sequence.

STRATEGY — Why this is stable even when UI changes slightly:
  - Use keyboard shortcuts instead of mouse clicks wherever possible.
  - Use window titles (text) not pixel coordinates.
  - Use Tab/Enter navigation for forms — these rarely change.
  - Only use pyautogui.click(x, y) as last resort; prefer hotkeys.

DEBUGGING A WORKFLOW:
  Run `python tools/record_workflow.py` to watch + log what you do manually.
  Then replicate those steps here.
"""

import logging
import time

import pyautogui
import pygetwindow as gw

from config.settings import settings
from core.executor   import OK, FAIL, ExecutionResult

log = logging.getLogger("jarvis.workflows.erp")


# ── Shared helper ─────────────────────────────────────────────────────────────

def _focus_erp(timeout: float = 6.0) -> bool:
    """Bring the ERP window to foreground. Returns True on success."""
    title = settings.get("erp_window_title", "ERP")
    deadline = time.time() + timeout
    while time.time() < deadline:
        wins = [w for w in gw.getAllWindows() if title.lower() in w.title.lower()]
        if wins:
            try:
                wins[0].activate()
                time.sleep(0.5)
                return True
            except Exception as e:
                log.warning("Could not activate ERP window: %s", e)
        time.sleep(0.3)
    log.error("ERP window '%s' not found.", title)
    return False


def _wait(seconds: float = 0.5):
    time.sleep(seconds)


# ── Workflows ─────────────────────────────────────────────────────────────────

def launch_erp() -> ExecutionResult:
    """Launch the ERP executable if path is configured."""
    import subprocess, os
    exe = settings.get("erp_executable", "")
    if not exe:
        return FAIL("erp_executable not set in config/jarvis.yaml")
    if not os.path.exists(exe):
        return FAIL(f"ERP executable not found: {exe}")
    subprocess.Popen([exe])
    _wait(3)
    return OK("ERP is starting.")


def open_po_entry_form() -> ExecutionResult:
    """
    Navigate to the PO Entry form inside the ERP.

    ── CUSTOMIZE THIS ──────────────────────────────────────────────────────
    Replace the steps below with the actual key sequence for YOUR ERP.

    Common approaches:
      a) Menu hotkey (e.g. Alt+P → Purchase → PO Entry)
      b) Search box (e.g. Ctrl+F → type "PO Entry" → Enter)
      c) Keyboard shortcut (e.g. F5 for PO module)

    Example for a menu-driven ERP:
      pyautogui.hotkey("alt", "p")   # Open "Purchase" menu
      _wait(0.4)
      pyautogui.press("down")        # Navigate to "PO Entry"
      pyautogui.press("enter")
    ────────────────────────────────────────────────────────────────────────
    """
    if not _focus_erp():
        return FAIL("ERP window not found.")

    log.info("Navigating to PO Entry form...")

    # ── REPLACE BELOW WITH YOUR REAL ERP NAVIGATION ──────────────────────
    # PLACEHOLDER — customize for your ERP:
    # pyautogui.hotkey("alt", "p")
    # _wait(0.4)
    # pyautogui.press("down")
    # pyautogui.press("enter")
    # ─────────────────────────────────────────────────────────────────────

    log.warning("PO Entry workflow not yet customized. Edit erp_workflows.py.")
    return OK("ERP focused. PO Entry workflow needs customization — see erp_workflows.py.")


def open_cutting_report(date: str = "today") -> ExecutionResult:
    """
    Open the Cutting Report for a given date.

    `date` is either "today" or "yesterday" (extracted from voice command).

    ── CUSTOMIZE THIS ──────────────────────────────────────────────────────
    Navigate to your report module and set the date filter.
    ────────────────────────────────────────────────────────────────────────
    """
    if not _focus_erp():
        return FAIL("ERP window not found.")

    log.info("Opening Cutting Report for: %s", date)

    # ── REPLACE BELOW WITH YOUR REAL ERP NAVIGATION ──────────────────────
    log.warning("Cutting Report workflow not yet customized. Edit erp_workflows.py.")
    return OK(f"ERP focused. Cutting Report ({date}) workflow needs customization.")


def open_production_report(date: str = "today") -> ExecutionResult:
    """
    Open the Production Report for a given date.

    ── CUSTOMIZE THIS ──────────────────────────────────────────────────────
    ────────────────────────────────────────────────────────────────────────
    """
    if not _focus_erp():
        return FAIL("ERP window not found.")

    log.info("Opening Production Report for: %s", date)

    # ── REPLACE BELOW WITH YOUR REAL ERP NAVIGATION ──────────────────────
    log.warning("Production Report workflow not yet customized. Edit erp_workflows.py.")
    return OK(f"ERP focused. Production Report ({date}) workflow needs customization.")
