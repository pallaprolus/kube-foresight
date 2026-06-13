"""Tests for dashboard routes using FastAPI TestClient."""

import pytest
from starlette.testclient import TestClient

from kube_foresight.dashboard import create_app


@pytest.fixture
def client():
    """Synchronous test client with lifespan context."""
    app = create_app()
    with TestClient(app) as c:
        yield c


# --- Health probes ---


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_readyz(client):
    resp = client.get("/readyz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["analysis_status"] == "idle"
    assert data["has_results"] is False


def test_readyz_after_analysis(client):
    client.post("/api/analyze", data={"mode": "mock", "namespace": "test", "seed": "42"})
    resp = client.get("/readyz")
    data = resp.json()
    assert data["analysis_status"] == "done"
    assert data["has_results"] is True


# --- Overview (landing page) ---


def test_overview_landing(client):
    """GET / returns the overview page with auto-analyzed data."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Cluster Overview" in resp.text


def test_overview_alias(client):
    """GET /overview also serves the overview page."""
    resp = client.get("/overview")
    assert resp.status_code == 200
    assert "Cluster Overview" in resp.text


def test_overview_auto_analyzes(client):
    """Overview auto-analyzes on first load — data is present without manual analysis."""
    resp = client.get("/")
    assert resp.status_code == 200
    # Should have deployment data from auto-analysis
    assert "Resource Utilization" in resp.text


def test_overview_has_settings(client):
    """Overview page has a settings panel with namespace, strategy, and analyze button."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert "settings-panel" in resp.text
    assert 'name="namespace"' in resp.text
    assert 'name="strategy"' in resp.text


def test_overview_has_namespace_dropdown(client):
    """Overview page renders namespace as a dropdown (not text input) for mock mode."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert '<select name="namespace"' in resp.text
    assert "demo-app" in resp.text


def test_overview_has_kpi_cards(client):
    """Overview page includes KPI cards after auto-analysis."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Monthly Savings" in resp.text


def test_overview_after_explicit_analysis(client):
    """After explicit analysis, overview shows the analyzed namespace."""
    client.post("/api/analyze", data={
        "mode": "mock", "namespace": "test-ns",
        "top_n": "5", "seed": "42",
    })
    resp = client.get("/overview")
    assert resp.status_code == 200
    assert "Cluster Overview" in resp.text
    assert "test-ns" in resp.text


# --- Backward-compatibility redirects ---


def test_executive_redirects_to_root(client):
    """GET /executive redirects to / (executive page removed)."""
    resp = client.get("/executive", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "/"


def test_patches_redirects_to_recommendations(client):
    """GET /patches redirects to /recommendations (patches merged)."""
    resp = client.get("/patches", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "/recommendations"


# --- Recommendations + Costs redirects without data ---


def test_recommendations_redirects_without_data(client):
    resp = client.get("/recommendations", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "/"


def test_costs_redirects_without_data(client):
    resp = client.get("/costs", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "/"


# --- API endpoints ---


def test_api_connect_mock(client):
    resp = client.post("/api/connect", data={"mode": "mock"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["connected"] is True


def test_api_analyze_mock(client):
    resp = client.post("/api/analyze", data={
        "mode": "mock",
        "namespace": "test-ns",
        "top_n": "5",
        "seed": "42",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["namespace"] == "test-ns"
    assert data["analyzed_deployments"] == 15
    assert len(data["profiles"]) == 15
    # Only deployments right-sized on BOTH CPU and memory are skipped.
    assert len(data["recommendations"]) == 14
    assert len(data["costs"]) == 14
    assert data["total_monthly_savings_usd"] > 0


# --- Page routes after analysis ---


def test_deployment_detail_after_analysis(client):
    report_resp = client.post("/api/analyze", data={
        "mode": "mock", "namespace": "test-ns", "top_n": "10", "seed": "42",
    })
    name = report_resp.json()["profiles"][0]["name"]
    resp = client.get(f"/deployments/{name}")
    assert resp.status_code == 200
    assert name in resp.text


def test_recommendations_page_after_analysis(client):
    client.post("/api/analyze", data={
        "mode": "mock", "namespace": "test-ns",
        "top_n": "5", "seed": "42",
    })
    resp = client.get("/recommendations")
    assert resp.status_code == 200
    assert "Recommendations" in resp.text


def test_recommendations_has_inline_patches(client):
    """Recommendations page includes inline YAML patches."""
    client.post("/api/analyze", data={
        "mode": "mock", "namespace": "test-ns",
        "top_n": "5", "seed": "42",
    })
    resp = client.get("/recommendations")
    assert resp.status_code == 200
    assert "apiVersion" in resp.text
    assert "Download All" in resp.text


def test_costs_page_after_analysis(client):
    client.post("/api/analyze", data={
        "mode": "mock", "namespace": "test-ns",
        "top_n": "5", "seed": "42",
    })
    resp = client.get("/costs")
    assert resp.status_code == 200
    assert "Cost Savings" in resp.text


def test_costs_has_cloud_comparison(client):
    """Cost Savings page includes multi-cloud comparison (from executive)."""
    client.post("/api/analyze", data={
        "mode": "mock", "namespace": "test-ns",
        "top_n": "5", "seed": "42",
    })
    resp = client.get("/costs")
    assert resp.status_code == 200
    assert "Cloud Cost Comparison" in resp.text
    assert "sizing-donut-chart" in resp.text


# --- API data endpoints ---


def test_api_timeseries(client):
    report_resp = client.post("/api/analyze", data={
        "mode": "mock", "namespace": "test-ns", "top_n": "10", "seed": "42",
    })
    name = report_resp.json()["profiles"][0]["name"]
    resp = client.get(f"/api/deployments/{name}/timeseries")
    assert resp.status_code == 200
    data = resp.json()
    assert "labels" in data
    assert "cpu" in data
    assert "memory" in data


def test_api_patches_download(client):
    client.post("/api/analyze", data={
        "mode": "mock", "namespace": "test-ns",
        "top_n": "5", "seed": "42",
    })
    resp = client.get("/api/patches/download")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert len(resp.content) > 0


# --- HTMX partials ---


def test_partial_connect(client):
    resp = client.post("/partials/connect", data={"mode": "mock"})
    assert resp.status_code == 200
    assert "&#10003;" in resp.text  # checkmark


def test_partial_analyze(client):
    resp = client.post("/partials/analyze", data={
        "mode": "mock",
        "namespace": "test-ns",
        "top_n": "5",
        "seed": "42",
    })
    assert resp.status_code == 200
    assert "HX-Redirect" in resp.headers or "Analysis complete" in resp.text


def test_partial_analyze_redirects_to_root(client):
    """After HTMX analysis, redirect goes to / (not /executive)."""
    resp = client.post("/partials/analyze", data={
        "mode": "mock", "namespace": "test-ns", "seed": "42",
    })
    assert resp.status_code == 200
    if "HX-Redirect" in resp.headers:
        assert resp.headers["HX-Redirect"] == "/"


# --- Static assets ---


def test_static_css(client):
    resp = client.get("/static/css/custom.css")
    assert resp.status_code == 200


def test_static_js(client):
    resp = client.get("/static/js/charts.js")
    assert resp.status_code == 200
    resp = client.get("/static/js/app.js")
    assert resp.status_code == 200
    resp = client.get("/static/js/clipboard.js")
    assert resp.status_code == 200
