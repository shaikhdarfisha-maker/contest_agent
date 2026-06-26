"""
metadata_store.py
=================
A local SQLite store for everything the production tracker must NOT hold:
internal contest/batch/test IDs, execution timestamps, per-run status, and
errors. The tracker stays the manual-fields-only source of truth; this is the
agent's own bookkeeping and duplicate-detection backstop.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Optional

from config import METADATA_DB
from modules.logger import get_logger

log = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS contests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    program         TEXT NOT NULL,
    module          TEXT NOT NULL,
    contest_name    TEXT NOT NULL,
    batch_name      TEXT NOT NULL,
    library_name    TEXT,
    library_link    TEXT,
    batch_id        TEXT,
    class_id        TEXT,
    contest_id      TEXT,
    test_ids_json   TEXT,
    a1_start        TEXT,
    a1_end          TEXT,
    windows_json    TEXT,
    status          TEXT NOT NULL DEFAULT 'created',
    tracker_row     INTEGER,
    created_at      TEXT NOT NULL,
    UNIQUE(program, batch_name)
);

CREATE TABLE IF NOT EXISTS run_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    contest_id  INTEGER,
    step        TEXT NOT NULL,
    level       TEXT NOT NULL,
    message     TEXT,
    created_at  TEXT NOT NULL,
    FOREIGN KEY (contest_id) REFERENCES contests(id)
);
"""


class MetadataStore:
    """Thin wrapper around SQLite with the few operations the agent needs."""

    def __init__(self, db_path: Path = METADATA_DB) -> None:
        self.db_path = db_path
        self._init_schema()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(_SCHEMA)
        log.debug("Metadata store ready at %s", self.db_path)

    # -- duplicate detection ----------------------------------------------- #
    def batch_exists(self, program: str, batch_name: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "SELECT 1 FROM contests WHERE program = ? AND batch_name = ? LIMIT 1",
                (program, batch_name),
            )
            return cur.fetchone() is not None

    # -- writes ------------------------------------------------------------ #
    def create_contest(self, **fields: Any) -> int:
        fields.setdefault("created_at", datetime.now().isoformat())
        fields.setdefault("status", "created")

        program = fields.get("program")
        batch_name = fields.get("batch_name")

        with self._conn() as conn:
            # If a record for this program+batch already exists (e.g. a re-run
            # of the same contest after an earlier failure), reuse and update it
            # rather than violating the UNIQUE constraint.
            existing = None
            if program is not None and batch_name is not None:
                existing = conn.execute(
                    "SELECT id FROM contests WHERE program = ? AND batch_name = ?",
                    (program, batch_name),
                ).fetchone()

            if existing is not None:
                row_id = int(existing["id"])
                assignments = ", ".join(f"{k} = ?" for k in fields)
                conn.execute(
                    f"UPDATE contests SET {assignments} WHERE id = ?",
                    (*fields.values(), row_id),
                )
                return row_id

            cols = ", ".join(fields.keys())
            placeholders = ", ".join("?" for _ in fields)
            cur = conn.execute(
                f"INSERT INTO contests ({cols}) VALUES ({placeholders})",
                tuple(fields.values()),
            )
            return int(cur.lastrowid)

    def update_contest(self, row_id: int, **fields: Any) -> None:
        if not fields:
            return
        assignments = ", ".join(f"{k} = ?" for k in fields)
        with self._conn() as conn:
            conn.execute(
                f"UPDATE contests SET {assignments} WHERE id = ?",
                (*fields.values(), row_id),
            )

    def log_step(
        self,
        step: str,
        message: str,
        level: str = "INFO",
        contest_id: Optional[int] = None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO run_logs (contest_id, step, level, message, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (contest_id, step, level, message, datetime.now().isoformat()),
            )

    # -- helpers ----------------------------------------------------------- #
    @staticmethod
    def dumps(value: Any) -> str:
        return json.dumps(value, default=str)
