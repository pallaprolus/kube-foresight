"""SQLite-backed audit trail for kube-foresight actions."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_CREATE_AUDIT_TABLE = """
CREATE TABLE IF NOT EXISTS audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_ms    INTEGER NOT NULL,
    action          TEXT    NOT NULL,
    deployment_name TEXT    NOT NULL,
    namespace       TEXT    NOT NULL DEFAULT '',
    dry_run         INTEGER NOT NULL DEFAULT 0,
    success         INTEGER NOT NULL DEFAULT 1,
    message         TEXT    NOT NULL DEFAULT '',
    source_ip       TEXT    NOT NULL DEFAULT '',
    patch_yaml      TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log (timestamp_ms);
CREATE INDEX IF NOT EXISTS idx_audit_deploy ON audit_log (deployment_name);
"""


@dataclass
class AuditEntry:
    id: int
    timestamp: datetime
    action: str
    deployment_name: str
    namespace: str
    dry_run: bool
    success: bool
    message: str
    source_ip: str
    patch_yaml: str


class AuditLog:
    """Persistent audit trail stored in SQLite."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            db_dir = Path.home() / ".kube-foresight"
            db_dir.mkdir(parents=True, exist_ok=True)
            db_path = db_dir / "audit.db"
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            conn.executescript(_CREATE_AUDIT_TABLE)
            conn.commit()
        finally:
            conn.close()

    def record(
        self,
        action: str,
        deployment_name: str,
        namespace: str = "",
        dry_run: bool = False,
        success: bool = True,
        message: str = "",
        source_ip: str = "",
        patch_yaml: str = "",
    ) -> int:
        """Record an audit event. Returns the row ID."""
        now_ms = int(time.time() * 1000)
        conn = self._connect()
        try:
            cursor = conn.execute(
                """INSERT INTO audit_log
                   (timestamp_ms, action, deployment_name, namespace,
                    dry_run, success, message, source_ip, patch_yaml)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (now_ms, action, deployment_name, namespace,
                 int(dry_run), int(success), message, source_ip, patch_yaml),
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def get_recent(self, limit: int = 50) -> list[AuditEntry]:
        """Get recent audit entries, newest first."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM audit_log ORDER BY timestamp_ms DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [self._row_to_entry(r) for r in rows]
        finally:
            conn.close()

    def get_for_deployment(self, deployment_name: str, limit: int = 20) -> list[AuditEntry]:
        """Get audit entries for a specific deployment."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM audit_log"
                " WHERE deployment_name = ?"
                " ORDER BY timestamp_ms DESC LIMIT ?",
                (deployment_name, limit),
            ).fetchall()
            return [self._row_to_entry(r) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> AuditEntry:
        return AuditEntry(
            id=row["id"],
            timestamp=datetime.fromtimestamp(row["timestamp_ms"] / 1000, tz=timezone.utc),
            action=row["action"],
            deployment_name=row["deployment_name"],
            namespace=row["namespace"],
            dry_run=bool(row["dry_run"]),
            success=bool(row["success"]),
            message=row["message"],
            source_ip=row["source_ip"],
            patch_yaml=row["patch_yaml"],
        )
