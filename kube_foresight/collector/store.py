"""SQLite-backed metrics store for Kubernetes Metrics API snapshots."""

from __future__ import annotations

import sqlite3
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from kube_foresight.models import ContainerMetrics, ResourceSpec

_DEFAULT_DB_DIR = Path.home() / ".kube-foresight"
_DEFAULT_DB_PATH = _DEFAULT_DB_DIR / "metrics.db"

_SCHEMA_VERSION = 1

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_ms    INTEGER NOT NULL,
    namespace       TEXT    NOT NULL,
    pod_name        TEXT    NOT NULL,
    container_name  TEXT    NOT NULL,
    deployment_name TEXT    NOT NULL DEFAULT '',
    cpu_nanocores   INTEGER NOT NULL,
    memory_bytes    INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_snap_ns_ts
    ON snapshots (namespace, timestamp_ms);
CREATE INDEX IF NOT EXISTS idx_snap_deploy_ts
    ON snapshots (namespace, deployment_name, timestamp_ms);

CREATE TABLE IF NOT EXISTS resource_specs (
    namespace       TEXT    NOT NULL,
    pod_name        TEXT    NOT NULL,
    container_name  TEXT    NOT NULL,
    cpu_request     REAL    NOT NULL DEFAULT 0,
    cpu_limit       REAL    NOT NULL DEFAULT 0,
    mem_request     REAL    NOT NULL DEFAULT 0,
    mem_limit       REAL    NOT NULL DEFAULT 0,
    updated_at      INTEGER NOT NULL,
    PRIMARY KEY (namespace, pod_name, container_name)
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


class MetricsStore:
    """SQLite persistence layer for Kubernetes metrics snapshots."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            db_path = _DEFAULT_DB_PATH
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            conn.executescript(_CREATE_TABLES)
            conn.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
                ("schema_version", str(_SCHEMA_VERSION)),
            )
            conn.commit()
        finally:
            conn.close()

    # ── Write operations ──────────────────────────────────────────

    def insert_snapshot(
        self,
        namespace: str,
        pod_name: str,
        container_name: str,
        deployment_name: str,
        cpu_nanocores: int,
        memory_bytes: int,
        timestamp_ms: int | None = None,
    ) -> None:
        """Insert a single metrics snapshot."""
        if timestamp_ms is None:
            timestamp_ms = int(time.time() * 1000)
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO snapshots
                   (timestamp_ms, namespace, pod_name, container_name,
                    deployment_name, cpu_nanocores, memory_bytes)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (timestamp_ms, namespace, pod_name, container_name,
                 deployment_name, cpu_nanocores, memory_bytes),
            )
            conn.commit()
        finally:
            conn.close()

    def insert_snapshots_batch(
        self,
        rows: list[tuple[int, str, str, str, str, int, int]],
    ) -> None:
        """Batch-insert snapshots. Each tuple: (ts_ms, ns, pod, container, deploy, cpu_nano, mem_bytes)."""
        conn = self._connect()
        try:
            conn.executemany(
                """INSERT INTO snapshots
                   (timestamp_ms, namespace, pod_name, container_name,
                    deployment_name, cpu_nanocores, memory_bytes)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )
            conn.commit()
        finally:
            conn.close()

    def upsert_resource_spec(
        self,
        namespace: str,
        pod_name: str,
        container_name: str,
        cpu_request: float,
        cpu_limit: float,
        mem_request: float,
        mem_limit: float,
    ) -> None:
        """Insert or update resource requests/limits for a container."""
        now_ms = int(time.time() * 1000)
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO resource_specs
                   (namespace, pod_name, container_name,
                    cpu_request, cpu_limit, mem_request, mem_limit, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (namespace, pod_name, container_name) DO UPDATE SET
                    cpu_request = excluded.cpu_request,
                    cpu_limit   = excluded.cpu_limit,
                    mem_request = excluded.mem_request,
                    mem_limit   = excluded.mem_limit,
                    updated_at  = excluded.updated_at""",
                (namespace, pod_name, container_name,
                 cpu_request, cpu_limit, mem_request, mem_limit, now_ms),
            )
            conn.commit()
        finally:
            conn.close()

    # ── Read operations ───────────────────────────────────────────

    def query_timeseries(
        self,
        namespace: str,
        lookback_hours: int = 168,
        step_seconds: int = 300,
    ) -> list[ContainerMetrics]:
        """Read historical snapshots and return ContainerMetrics aligned to step_seconds grid."""
        now_ms = int(time.time() * 1000)
        start_ms = now_ms - (lookback_hours * 3600 * 1000)
        step_ms = step_seconds * 1000

        conn = self._connect()
        try:
            # Downsample: group into step-sized buckets using integer division
            rows = conn.execute(
                """SELECT
                       (timestamp_ms / ?) * ? AS bucket_ms,
                       pod_name,
                       container_name,
                       deployment_name,
                       CAST(AVG(cpu_nanocores) AS INTEGER) AS avg_cpu,
                       CAST(AVG(memory_bytes) AS INTEGER)  AS avg_mem
                   FROM snapshots
                   WHERE namespace = ? AND timestamp_ms >= ?
                   GROUP BY bucket_ms, pod_name, container_name, deployment_name
                   ORDER BY pod_name, container_name, bucket_ms""",
                (step_ms, step_ms, namespace, start_ms),
            ).fetchall()

            # Load resource specs
            specs = {}
            spec_rows = conn.execute(
                """SELECT pod_name, container_name,
                          cpu_request, cpu_limit, mem_request, mem_limit
                   FROM resource_specs
                   WHERE namespace = ?""",
                (namespace,),
            ).fetchall()
            for sr in spec_rows:
                key = f"{sr['pod_name']}:{sr['container_name']}"
                specs[key] = {
                    "cpu_request": sr["cpu_request"],
                    "cpu_limit": sr["cpu_limit"],
                    "mem_request": sr["mem_request"],
                    "mem_limit": sr["mem_limit"],
                }
        finally:
            conn.close()

        # Group rows by (pod_name, container_name)
        grouped: dict[str, list] = defaultdict(list)
        deploy_map: dict[str, str] = {}
        for row in rows:
            key = f"{row['pod_name']}:{row['container_name']}"
            grouped[key].append(row)
            if row["deployment_name"]:
                deploy_map[key] = row["deployment_name"]

        # Build ContainerMetrics objects
        results: list[ContainerMetrics] = []
        for key, bucket_rows in grouped.items():
            pod_name, container_name = key.split(":", 1)
            deployment_name = deploy_map.get(key, pod_name)

            cpu_series = [
                (
                    datetime.fromtimestamp(r["bucket_ms"] / 1000, tz=timezone.utc),
                    r["avg_cpu"] / 1_000_000_000,  # nanocores → cores
                )
                for r in bucket_rows
            ]
            mem_series = [
                (
                    datetime.fromtimestamp(r["bucket_ms"] / 1000, tz=timezone.utc),
                    float(r["avg_mem"]),  # already in bytes
                )
                for r in bucket_rows
            ]

            spec_info = specs.get(key, {})
            cpu_req = spec_info.get("cpu_request", 0.1)
            cpu_lim = spec_info.get("cpu_limit", cpu_req * 2)
            mem_req = spec_info.get("mem_request", 128 * 1024 * 1024)
            mem_lim = spec_info.get("mem_limit", mem_req * 2)

            results.append(
                ContainerMetrics(
                    container_name=container_name,
                    pod_name=pod_name,
                    deployment_name=deployment_name,
                    namespace=namespace,
                    cpu_usage=cpu_series,
                    memory_usage=mem_series,
                    cpu_spec=ResourceSpec(request=cpu_req, limit=cpu_lim),
                    memory_spec=ResourceSpec(request=mem_req, limit=mem_lim),
                )
            )

        return results

    def get_snapshot_count(self, namespace: str | None = None) -> int:
        """Return total number of snapshots, optionally filtered by namespace."""
        conn = self._connect()
        try:
            if namespace:
                row = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM snapshots WHERE namespace = ?",
                    (namespace,),
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) AS cnt FROM snapshots").fetchone()
            return row["cnt"]
        finally:
            conn.close()

    # ── Maintenance ───────────────────────────────────────────────

    def downsample_old_data(self, full_res_hours: int = 168) -> int:
        """Downsample data older than full_res_hours to 30-minute averages.

        Returns number of rows removed.
        """
        now_ms = int(time.time() * 1000)
        cutoff_ms = now_ms - (full_res_hours * 3600 * 1000)
        downsample_step_ms = 30 * 60 * 1000  # 30 minutes

        conn = self._connect()
        try:
            # Count rows before
            before = conn.execute(
                "SELECT COUNT(*) AS cnt FROM snapshots WHERE timestamp_ms < ?",
                (cutoff_ms,),
            ).fetchone()["cnt"]

            if before == 0:
                return 0

            # Create downsampled rows
            conn.execute(
                """INSERT INTO snapshots
                   (timestamp_ms, namespace, pod_name, container_name,
                    deployment_name, cpu_nanocores, memory_bytes)
                   SELECT
                       (timestamp_ms / ?) * ? AS bucket_ms,
                       namespace, pod_name, container_name, deployment_name,
                       CAST(AVG(cpu_nanocores) AS INTEGER),
                       CAST(AVG(memory_bytes) AS INTEGER)
                   FROM snapshots
                   WHERE timestamp_ms < ?
                   GROUP BY bucket_ms, namespace, pod_name, container_name, deployment_name""",
                (downsample_step_ms, downsample_step_ms, cutoff_ms),
            )

            # Delete original high-res rows (the downsampled rows have aligned timestamps)
            conn.execute(
                """DELETE FROM snapshots
                   WHERE timestamp_ms < ?
                     AND (timestamp_ms % ?) != 0""",
                (cutoff_ms, downsample_step_ms),
            )

            after = conn.execute(
                "SELECT COUNT(*) AS cnt FROM snapshots WHERE timestamp_ms < ?",
                (cutoff_ms,),
            ).fetchone()["cnt"]

            conn.commit()
            return before - after
        finally:
            conn.close()

    def purge_old_data(self, retention_hours: int = 720) -> int:
        """Delete all data older than retention_hours. Returns rows deleted."""
        now_ms = int(time.time() * 1000)
        cutoff_ms = now_ms - (retention_hours * 3600 * 1000)

        conn = self._connect()
        try:
            cursor = conn.execute(
                "DELETE FROM snapshots WHERE timestamp_ms < ?", (cutoff_ms,)
            )
            # Also clean up stale resource specs
            conn.execute(
                "DELETE FROM resource_specs WHERE updated_at < ?", (cutoff_ms,)
            )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()
