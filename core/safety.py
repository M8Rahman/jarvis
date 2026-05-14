"""
core/safety.py
──────────────
Safety layer: emergency stop, action validation, and state tracking.

Rules:
  • JARVIS never executes two actions simultaneously.
  • Any module can call safety.engage_stop() to halt everything.
  • PyAutoGUI failsafe (top-left corner) is always enabled — see executor.py.
  • All actions are logged to logs/actions.log for audit.
"""

import logging
import datetime

from core.state import AssistantState

log = logging.getLogger("jarvis.safety")

# Separate audit log for every executed action
audit_log = logging.getLogger("jarvis.audit")
_fh = logging.FileHandler("logs/actions.log", encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
audit_log.addHandler(_fh)
audit_log.setLevel(logging.INFO)


class SafetyGuard:

    def __init__(self, state: AssistantState):
        self._state = state

    @property
    def is_stopped(self) -> bool:
        return self._state.emergency_stop

    def engage_stop(self):
        """Immediately set emergency stop flag. All handlers must check this."""
        self._state.emergency_stop = True
        log.warning("Emergency stop engaged.")

    def reset_stop(self):
        """Clear emergency stop (only call manually / at startup)."""
        self._state.emergency_stop = False
        log.info("Emergency stop cleared.")

    def log_action(self, action_name: str, params: dict, success: bool, note: str = ""):
        """Write to audit log."""
        status = "OK" if success else "FAIL"
        audit_log.info("%s | %s | params=%s | %s", action_name, status, params, note)
