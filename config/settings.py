"""
config/settings.py
──────────────────
Centralised configuration. Single source of truth for all modules.

Usage:
    from config.settings import settings
    val = settings.get("whisper_model", "base")

All keys and defaults are defined in _DEFAULTS below.
User overrides come from config/jarvis.yaml — no code changes needed.

Also exposes setup_logging() — call once from main.py at startup.
"""

import logging
import logging.handlers
import os

log = logging.getLogger("jarvis.settings")

# ── Defaults ──────────────────────────────────────────────────────────────────
_DEFAULTS: dict = {
    # Whisper STT
    "whisper_model": "base",

    # TTS
    "tts_rate":       165,
    "tts_volume":     0.9,
    "tts_voice_name": "",

    # ERP
    "erp_window_title": "ERP",
    "erp_executable":   "",

    # Automation
    "action_delay":         0.3,
    "confirmation_timeout": 8.0,

    # Outlook
    "outlook_search_folder": "Inbox",
    "outlook_max_search":    200,
    "outlook_launch_wait":   4.0,

    # Attachments
    "attachment_root": "E:/Projects/JARVIS/attachments",

    # Memory
    "memory_db_path": "E:/Projects/JARVIS/memory/jarvis_memory.db",

    # Logging
    "log_dir":          "E:/Projects/JARVIS/logs",
    "log_level":        "INFO",
    "log_max_bytes":    5_242_880,
    "log_backup_count": 3,
}


class _Settings(dict):
    """Dict that loads jarvis.yaml overrides on top of _DEFAULTS."""

    def __init__(self):
        super().__init__(_DEFAULTS)
        self._load_yaml()
        self._ensure_directories()

    def _load_yaml(self):
        yaml_path = os.path.join(os.path.dirname(__file__), "jarvis.yaml")
        if not os.path.exists(yaml_path):
            return
        try:
            import yaml
            with open(yaml_path, encoding="utf-8") as f:
                overrides = yaml.safe_load(f) or {}
            self.update(overrides)
            log.info("Config loaded from %s", yaml_path)
        except Exception as exc:
            log.warning("Could not load jarvis.yaml: %s", exc)

    def _ensure_directories(self):
        """Create all required directories at startup."""
        dirs = [
            self.get("log_dir", ""),
            self.get("attachment_root", ""),
            os.path.dirname(self.get("memory_db_path", "")),
        ]
        for d in dirs:
            if d:
                os.makedirs(d, exist_ok=True)

    def str(self, key: str, default: str = "") -> str:
        return str(self.get(key, default))

    def int(self, key: str, default: int = 0) -> int:
        return int(self.get(key, default))

    def float(self, key: str, default: float = 0.0) -> float:
        return float(self.get(key, default))


settings = _Settings()


def setup_logging():
    """Configure rotating file + console logging. Call once from main.py."""
    log_dir   = settings.str("log_dir")
    log_level = getattr(logging, settings.str("log_level").upper(), logging.INFO)
    log_file  = os.path.join(log_dir, "jarvis.log")

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fh = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=settings.int("log_max_bytes", 5_242_880),
        backupCount=settings.int("log_backup_count", 3),
        encoding="utf-8",
    )
    fh.setFormatter(fmt)
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(log_level)
    root.handlers.clear()
    root.addHandler(fh)
    root.addHandler(ch)
    logging.getLogger("jarvis.settings").info(
        "Logging ready → %s  level=%s", log_file, settings.str("log_level")
    )
