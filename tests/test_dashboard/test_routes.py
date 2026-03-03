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


def test_home_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "kube-foresight" in resp.text
    assert "Demo Mode" in resp.text


def test_overview_redirects_without_data(client):
    resp = client.get("/overview", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "/"


def test_recommendations_redirects_without_data(client):
    resp = client.get("/recommendations", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "/"


def test_costs_redirects_without_data(client):
    resp = client.get("/costs", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "/"


def test_patches_redirects_without_data(client):
    resp = client.get("/patches", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "/"


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
    assert data["analyzed_deployments"] == 5
    assert len(data["profiles"]) == 5
    assert len(data["recommendations"]) == 5
    assert len(data["costs"]) == 5
    assert data["total_monthly_savings_usd"] > 0


def test_overview_after_analysis(client):
    # First run analysis
    client.post("/api/analyze", data={"mode": "mock", "namespace": "test-ns", "top_n": "5", "seed": "42"})
    # Then access overview
    resp = client.get("/overview")
    assert resp.status_code == 200
    assert "Cluster Overview" in resp.text
    assert "test-ns" in resp.text


def test_deployment_detail_after_analysis(client):
    # Run analysis, get a deployment name from the results
    report_resp = client.post("/api/analyze", data={
        "mode": "mock", "namespace": "test-ns", "top_n": "10", "seed": "42",
    })
    name = report_resp.json()["profiles"][0]["name"]
    resp = client.get(f"/deployments/{name}")
    assert resp.status_code == 200
    assert name in resp.text


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
    client.post("/api/analyze", data={"mode": "mock", "namespace": "test-ns", "top_n": "5", "seed": "42"})
    resp = client.get("/api/patches/download")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert len(resp.content) > 0


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


def test_recommendations_page_after_analysis(client):
    client.post("/api/analyze", data={"mode": "mock", "namespace": "test-ns", "top_n": "5", "seed": "42"})
    resp = client.get("/recommendations")
    assert resp.status_code == 200
    assert "Recommendations" in resp.text


def test_costs_page_after_analysis(client):
    client.post("/api/analyze", data={"mode": "mock", "namespace": "test-ns", "top_n": "5", "seed": "42"})
    resp = client.get("/costs")
    assert resp.status_code == 200
    assert "Cost Savings" in resp.text


def test_patches_page_after_analysis(client):
    client.post("/api/analyze", data={"mode": "mock", "namespace": "test-ns", "top_n": "5", "seed": "42"})
    resp = client.get("/patches")
    assert resp.status_code == 200
    assert "Kubernetes Patches" in resp.text
    assert "apiVersion" in resp.text


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
