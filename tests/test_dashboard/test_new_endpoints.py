"""Tests for new dashboard endpoints: scheduler status, audit log."""

import pytest
from starlette.testclient import TestClient

from kube_foresight.dashboard import create_app


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_scheduler_status_disabled(client):
    resp = client.get("/api/scheduler/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is False


def test_audit_log_empty(client):
    resp = client.get("/api/audit")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 0


def test_audit_log_after_analysis(client):
    # Audit log shouldn't have entries from analysis alone (only from patches)
    client.post("/api/analyze", data={"mode": "mock", "namespace": "test", "seed": "42"})
    resp = client.get("/api/audit")
    data = resp.json()
    assert isinstance(data, list)


def test_forecast_api_after_analysis(client):
    report = client.post("/api/analyze", data={
        "mode": "mock", "namespace": "test-ns", "top_n": "10", "seed": "42",
    }).json()
    name = report["profiles"][0]["name"]
    resp = client.get(f"/api/deployments/{name}/forecast")
    assert resp.status_code == 200
    data = resp.json()
    assert data["deployment_name"] == name
    assert "cpu_forecast" in data
    assert "memory_forecast" in data
    assert data["risk_level"] in ("ok", "warning", "critical")


def test_forecast_api_not_found(client):
    client.post("/api/analyze", data={"mode": "mock", "namespace": "test", "seed": "42"})
    resp = client.get("/api/deployments/nonexistent/forecast")
    assert resp.status_code == 404


def test_forecast_api_no_analysis(client):
    resp = client.get("/api/deployments/test/forecast")
    assert resp.status_code == 400


def test_namespaces_discovery_no_path(client):
    resp = client.post("/partials/namespaces", data={"db_path": ""})
    assert resp.status_code == 200
    assert "Enter a DB path first" in resp.text


def test_namespaces_discovery_with_db(client, tmp_path):
    import time

    from kube_foresight.collector.store import MetricsStore

    db = tmp_path / "test.db"
    store = MetricsStore(db_path=db)
    ts = int(time.time() * 1000)
    store.insert_snapshot(
        "my-ns", "pod-1-123", "app", "deploy-1",
        100_000_000, 64 * 1024 * 1024, timestamp_ms=ts,
    )

    resp = client.post("/partials/namespaces", data={"db_path": str(db)})
    assert resp.status_code == 200
    assert "my-ns" in resp.text
    assert "1 deploys" in resp.text
