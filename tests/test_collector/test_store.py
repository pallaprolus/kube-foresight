"""Tests for the SQLite MetricsStore."""

import time

import pytest

from kube_foresight.collector.store import MetricsStore


@pytest.fixture
def store(tmp_path):
    return MetricsStore(db_path=tmp_path / "test_metrics.db")


def _ts(minutes_ago: int) -> int:
    """Return epoch ms for N minutes ago."""
    return int((time.time() - minutes_ago * 60) * 1000)


def test_insert_and_count(store):
    store.insert_snapshot("default", "pod-a-xyz-123", "app", "pod-a", 100_000_000, 128 * 1024 * 1024)
    assert store.get_snapshot_count() == 1
    assert store.get_snapshot_count("default") == 1
    assert store.get_snapshot_count("other") == 0


def test_batch_insert(store):
    now_ms = int(time.time() * 1000)
    rows = [
        (now_ms, "default", f"pod-{i}-xyz-123", "app", f"pod-{i}", 50_000_000 * i, 64 * 1024 * 1024 * i)
        for i in range(1, 6)
    ]
    store.insert_snapshots_batch(rows)
    assert store.get_snapshot_count("default") == 5


def test_upsert_resource_spec(store):
    store.upsert_resource_spec("default", "pod-a-xyz-123", "app", 0.5, 1.0, 256 * 1024 * 1024, 512 * 1024 * 1024)
    # Upsert again with different values — should not fail
    store.upsert_resource_spec("default", "pod-a-xyz-123", "app", 0.3, 0.6, 128 * 1024 * 1024, 256 * 1024 * 1024)
    # Check that specs are used in query
    assert store.get_snapshot_count() == 0  # no snapshots yet, just specs


def test_query_timeseries_empty(store):
    result = store.query_timeseries("default", lookback_hours=1, step_seconds=60)
    assert result == []


def test_query_timeseries_returns_container_metrics(store):
    """Insert multiple snapshots and verify they're returned as ContainerMetrics."""
    step_ms = 300_000  # 5 min
    # Insert 10 data points over 50 minutes
    rows = []
    for i in range(10):
        ts = _ts(50 - i * 5)  # spread over last 50 minutes
        # Align to step boundary for predictable grouping
        ts = (ts // step_ms) * step_ms
        rows.append((ts, "prod", "web-abc-123", "nginx", "web", 200_000_000, 256 * 1024 * 1024))
    store.insert_snapshots_batch(rows)
    store.upsert_resource_spec("prod", "web-abc-123", "nginx", 0.5, 1.0, 512 * 1024 * 1024, 1024 * 1024 * 1024)

    metrics = store.query_timeseries("prod", lookback_hours=2, step_seconds=300)
    assert len(metrics) == 1

    m = metrics[0]
    assert m.container_name == "nginx"
    assert m.pod_name == "web-abc-123"
    assert m.deployment_name == "web"
    assert m.namespace == "prod"
    assert m.cpu_spec.request == 0.5
    assert m.cpu_spec.limit == 1.0
    assert m.memory_spec.request == 512 * 1024 * 1024
    assert len(m.cpu_usage) > 0
    # CPU should be ~0.2 cores (200M nanocores / 1B)
    cpu_values = [v for _, v in m.cpu_usage]
    assert all(0.15 < v < 0.25 for v in cpu_values)


def test_query_timeseries_default_specs(store):
    """When no resource spec exists, reasonable defaults are used."""
    store.insert_snapshot("ns", "pod-abc-123", "app", "pod", 100_000_000, 64 * 1024 * 1024, timestamp_ms=_ts(5))
    metrics = store.query_timeseries("ns", lookback_hours=1, step_seconds=300)
    assert len(metrics) == 1
    m = metrics[0]
    # Default specs
    assert m.cpu_spec.request == 0.1
    assert m.cpu_spec.limit == 0.2  # 2x request
    assert m.memory_spec.request == 128 * 1024 * 1024


def test_query_multiple_containers(store):
    """Multiple pods/containers should produce multiple ContainerMetrics."""
    ts = _ts(5)
    store.insert_snapshot("ns", "api-abc-123", "api", "api", 100_000_000, 64 * 1024 * 1024, timestamp_ms=ts)
    store.insert_snapshot("ns", "web-def-456", "web", "web", 200_000_000, 128 * 1024 * 1024, timestamp_ms=ts)
    metrics = store.query_timeseries("ns", lookback_hours=1, step_seconds=300)
    assert len(metrics) == 2
    names = {m.deployment_name for m in metrics}
    assert names == {"api", "web"}


def test_purge_old_data(store):
    # Insert old data (2 hours ago) and recent data (5 min ago)
    store.insert_snapshot("ns", "pod-a-123", "app", "pod-a", 100_000_000, 64 * 1024 * 1024, timestamp_ms=_ts(120))
    store.insert_snapshot("ns", "pod-a-123", "app", "pod-a", 100_000_000, 64 * 1024 * 1024, timestamp_ms=_ts(5))
    assert store.get_snapshot_count() == 2

    deleted = store.purge_old_data(retention_hours=1)
    assert deleted == 1
    assert store.get_snapshot_count() == 1


def test_purge_no_data(store):
    deleted = store.purge_old_data(retention_hours=1)
    assert deleted == 0


def test_downsample_old_data(store):
    """Downsampling should reduce row count for old data."""
    step_ms = 300_000  # 5 min intervals
    # Insert 60 data points: 30 old (10-15 hours ago) + 30 recent (0-2.5 hours ago)
    rows = []
    for i in range(30):
        # Old data: 10-12.5 hours ago (5 min apart)
        ts_old = _ts(600 + i * 5)
        ts_old = (ts_old // step_ms) * step_ms
        rows.append((ts_old, "ns", "pod-a-123", "app", "pod-a", 100_000_000, 64 * 1024 * 1024))
        # Recent data: 0-2.5 hours ago
        ts_new = _ts(i * 5)
        ts_new = (ts_new // step_ms) * step_ms
        rows.append((ts_new, "ns", "pod-a-123", "app", "pod-a", 200_000_000, 128 * 1024 * 1024))
    store.insert_snapshots_batch(rows)

    before = store.get_snapshot_count()
    # Downsample data older than 3 hours
    removed = store.downsample_old_data(full_res_hours=3)
    after = store.get_snapshot_count()

    # Old data should have been compressed (fewer rows)
    assert after < before
    assert removed > 0


def test_db_path_created(tmp_path):
    """DB directory is created if it doesn't exist."""
    deep_path = tmp_path / "a" / "b" / "c" / "test.db"
    store = MetricsStore(db_path=deep_path)
    assert deep_path.exists()
    assert store.db_path == deep_path
