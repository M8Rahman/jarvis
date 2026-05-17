"""
core/executor.py
────────────────
Receives a confirmed Action and executes it.

Phase 1.3 changes:
  - All Bangla text removed. English only.
  - Error messages updated to English.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import pyautogui
import pygetwindow as gw

from core.intent  import Action
from core.tts     import Speaker
from core.safety  import SafetyGuard
from core.memory  import memory

log = logging.getLogger("jarvis.executor")

pyautogui.PAUSE    = 0.3
pyautogui.FAILSAFE = True


# ── Result ────────────────────────────────────────────────────────────────────

@dataclass
class ExecutionResult:
    success: bool
    message: str = ""


def OK(msg: str = "Done.")    -> ExecutionResult: return ExecutionResult(True,  msg)
def FAIL(msg: str = "Error.") -> ExecutionResult: return ExecutionResult(False, msg)


# ── Executor ──────────────────────────────────────────────────────────────────

class ActionExecutor:

    def __init__(self, speaker: Speaker, safety: SafetyGuard):
        self.speaker = speaker
        self.safety  = safety
        self._build_handlers()

    def run(self, action: Action) -> ExecutionResult:
        handler = self._handlers.get(action.name)
        if not handler:
            return FAIL(f"No handler registered for action: {action.name}")
        try:
            result = handler(action)
        except pyautogui.FailSafeException:
            log.warning("PyAutoGUI failsafe triggered.")
            self.safety.engage_stop()
            result = FAIL("Failsafe triggered: mouse moved to screen corner. Stopped.")
        except Exception as exc:
            log.exception("Handler '%s' raised: %s", action.name, exc)
            result = FAIL(str(exc))

        # Audit log every execution
        self.safety.log_action(action.name, action.params, result.success, result.message)
        return result

    def _build_handlers(self):
        self._handlers = {
            # ── Outlook / PO ────────────────────────────────────────────
            "find_collection_po":  self._h_find_collection_po,
            "open_outlook":        self._h_open_outlook,
            "read_latest_po":      self._h_read_latest_po,
            # ── ERP ─────────────────────────────────────────────────────
            "po_entry":            self._h_po_entry,
            "cutting_report":      self._h_cutting_report,
            "production_report":   self._h_production_report,
            "open_erp":            self._h_open_erp,
            # ── Browser ─────────────────────────────────────────────────
            "google_search":       self._h_google_search,
            # ── Utility ─────────────────────────────────────────────────
            "take_screenshot":     self._h_take_screenshot,
        }

    def _check_stop(self) -> bool:
        return self.safety.is_stopped

    # ── Outlook handlers ──────────────────────────────────────────────────────

    def _h_find_collection_po(self, action: Action) -> ExecutionResult:
        from workflows.outlook_workflows import find_collection_po
        if self._check_stop(): return FAIL("Stopped by user.")
        if not action.params.get("buyer"):
            return FAIL(
                "Please say the buyer name with the command. "
                "Example: Find Cecil Collection 10.2"
            )
        return find_collection_po(action.params)

    def _h_open_outlook(self, action: Action) -> ExecutionResult:
        from workflows.outlook_workflows import open_outlook
        if self._check_stop(): return FAIL("Stopped by user.")
        return open_outlook()

    def _h_read_latest_po(self, action: Action) -> ExecutionResult:
        from workflows.outlook_workflows import find_latest_buyer_po
        if self._check_stop(): return FAIL("Stopped by user.")
        return find_latest_buyer_po()

    # ── ERP handlers ──────────────────────────────────────────────────────────

    def _h_po_entry(self, action: Action) -> ExecutionResult:
        from workflows.erp_workflows import open_po_entry_form
        if self._check_stop(): return FAIL("Stopped by user.")
        return open_po_entry_form()

    def _h_cutting_report(self, action: Action) -> ExecutionResult:
        from workflows.erp_workflows import open_cutting_report
        if self._check_stop(): return FAIL("Stopped by user.")
        return open_cutting_report(action.params.get("date", "today"))

    def _h_production_report(self, action: Action) -> ExecutionResult:
        from workflows.erp_workflows import open_production_report
        if self._check_stop(): return FAIL("Stopped by user.")
        return open_production_report(action.params.get("date", "today"))

    def _h_open_erp(self, action: Action) -> ExecutionResult:
        from workflows.erp_workflows import launch_erp
        if self._check_stop(): return FAIL("Stopped by user.")
        return launch_erp()

    # ── Browser handler ───────────────────────────────────────────────────────

    def _h_google_search(self, action: Action) -> ExecutionResult:
        from workflows.browser_workflows import google_search
        if self._check_stop(): return FAIL("Stopped by user.")
        query = action.params.get("query", "")
        if not query:
            return FAIL("No search query found in command.")
        return google_search(query)

    # ── Utility handler ───────────────────────────────────────────────────────

    def _h_take_screenshot(self, action: Action) -> ExecutionResult:
        import datetime, os
        from config.settings import settings
        if self._check_stop(): return FAIL("Stopped by user.")
        ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(settings.str("log_dir"), f"screenshot_{ts}.png")
        pyautogui.screenshot(path)
        log.info("Screenshot saved: %s", path)
        return OK(f"Screenshot saved to {path}")
