"""
core/safety.py
──────────────
Safety layer: emergency stop and audit logging.

FIX: audit log now writes to configured log_dir (E:/Projects/JARVIS/logs/)
instead of hardcoded relative 'logs/' path.
"""

import logging
import logging.handlers
import os

from core.state import AssistantState

log = logging.getLogger("jarvis.safety")


def _build_audit_logger() -> logging.Logger:
    """Build audit logger pointing to configured log directory."""
    from config.settings import settings
    log_dir  = settings.str("log_dir", "logs")
    log_path = os.path.join(log_dir, "actions.log")
    os.makedirs(log_dir, exist_ok=True)

    audit = logging.getLogger("jarvis.audit")
    if not audit.handlers:   # avoid duplicate handlers on re-import
        fh = logging.handlers.RotatingFileHandler(
            log_path, maxBytes=2_097_152, backupCount=2, encoding="utf-8"
        )
        fh.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
        audit.addHandler(fh)
        audit.setLevel(logging.INFO)
    return audit


class SafetyGuard:

    def __init__(self, state: AssistantState):
        self._state      = state
        self._audit_log  = _build_audit_logger()

    @property
    def is_stopped(self) -> bool:
        return self._state.emergency_stop

    def engage_stop(self):
        self._state.emergency_stop = True
        log.warning("Emergency stop engaged.")

    def reset_stop(self):
        self._state.emergency_stop = False
        log.info("Emergency stop cleared.")

    def log_action(self, action_name: str, params: dict,
                   success: bool, note: str = ""):
        status = "OK" if success else "FAIL"
        self._audit_log.info(
            "%s | %s | params=%s | %s", action_name, status, params, note
        )
