"""
core/memory.py
───────────────
Lightweight SQLite memory for JARVIS.

Two tables only:
  command_history  — every command heard, intent matched, result
  workflow_log     — successful workflow executions with full params

Design principles:
  - No ORM. Plain SQL. Easy to inspect with DB Browser for SQLite.
  - Atomic writes only (SQLite handles this natively).
  - Query methods kept simple — no complex joins.
  - File location from settings["memory_db_path"].

Usage:
    from core.memory import memory
    memory.log_command("find Cecil coll 10.5", "find_collection_po", True)
    memory.log_workflow("find_collection_po", {"buyer":"Cecil","coll":"2026105"}, True)
    rows = memory.recent_commands(10)
"""

from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from config.settings import settings

log = logging.getLogger("jarvis.memory")

# ── Schema ────────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS command_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT    NOT NULL,
    raw_text    TEXT    NOT NULL,
    intent      TEXT,
    params      TEXT,
    success     INTEGER NOT NULL DEFAULT 0,
    note        TEXT
);

CREATE TABLE IF NOT EXISTS workflow_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp    TEXT    NOT NULL,
    workflow     TEXT    NOT NULL,
    params       TEXT,
    success      INTEGER NOT NULL DEFAULT 0,
    duration_ms  INTEGER,
    note         TEXT
);

CREATE INDEX IF NOT EXISTS idx_cmd_intent   ON command_history(intent);
CREATE INDEX IF NOT EXISTS idx_cmd_ts       ON command_history(timestamp);
CREATE INDEX IF NOT EXISTS idx_wf_workflow  ON workflow_log(workflow);
CREATE INDEX IF NOT EXISTS idx_wf_ts        ON workflow_log(timestamp);
"""


# ── Memory class ──────────────────────────────────────────────────────────────

class Memory:

    def __init__(self):
        self._db_path = settings.str("memory_db_path")
        self._ensure_db_dir()
        self._init_schema()
        log.info("Memory initialised at %s", self._db_path)

    def _ensure_db_dir(self):
        d = os.path.dirname(self._db_path)
        if d:
            os.makedirs(d, exist_ok=True)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self._db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self):
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    # ── Write methods ─────────────────────────────────────────────────────

    def log_command(
        self,
        raw_text: str,
        intent:   str | None,
        success:  bool,
        params:   dict | None = None,
        note:     str = "",
    ):
        """Record every command attempt — success or failure."""
        import json
        ts = datetime.now().isoformat(sep=" ", timespec="seconds")
        params_str = json.dumps(params, ensure_ascii=False) if params else None
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO command_history
                   (timestamp, raw_text, intent, params, success, note)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (ts, raw_text, intent, params_str, int(success), note),
            )

    def log_workflow(
        self,
        workflow:    str,
        params:      dict | None,
        success:     bool,
        duration_ms: int | None = None,
        note:        str = "",
    ):
        """Record a completed workflow execution."""
        import json
        ts = datetime.now().isoformat(sep=" ", timespec="seconds")
        params_str = json.dumps(params, ensure_ascii=False) if params else None
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO workflow_log
                   (timestamp, workflow, params, success, duration_ms, note)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (ts, workflow, params_str, int(success), duration_ms, note),
            )

    # ── Read methods ──────────────────────────────────────────────────────

    def recent_commands(self, n: int = 20) -> list[dict]:
        """Return the n most recent command history rows."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM command_history ORDER BY id DESC LIMIT ?", (n,)
            ).fetchall()
        return [dict(r) for r in rows]

    def recent_workflows(self, n: int = 20) -> list[dict]:
        """Return the n most recent workflow log rows."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM workflow_log ORDER BY id DESC LIMIT ?", (n,)
            ).fetchall()
        return [dict(r) for r in rows]

    def workflow_success_rate(self, workflow: str) -> float:
        """Return success rate (0.0–1.0) for a given workflow name."""
        with self._conn() as conn:
            row = conn.execute(
                """SELECT COUNT(*) as total,
                          SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) as ok
                   FROM workflow_log WHERE workflow = ?""",
                (workflow,),
            ).fetchone()
        if not row or row["total"] == 0:
            return 0.0
        return row["ok"] / row["total"]

    def last_successful_params(self, workflow: str) -> dict | None:
        """
        Return the params dict from the most recent SUCCESSFUL run
        of a workflow. Useful for 'repeat last action' features later.
        """
        import json
        with self._conn() as conn:
            row = conn.execute(
                """SELECT params FROM workflow_log
                   WHERE workflow = ? AND success = 1
                   ORDER BY id DESC LIMIT 1""",
                (workflow,),
            ).fetchone()
        if row and row["params"]:
            return json.loads(row["params"])
        return None


# ── Singleton ─────────────────────────────────────────────────────────────────
memory = Memory()
