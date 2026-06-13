"""Tests for the dashboard AnalysisService."""

import pytest

from kube_foresight.dashboard.service import AnalysisService, AnalysisStatus


@pytest.fixture
def service():
    return AnalysisService()


def test_initial_state(service):
    assert service.status == AnalysisStatus.IDLE
    assert not service.has_results
    assert service.get_report() is None


def test_test_connection_mock(service):
    ok, msg = service.test_connection(mode="mock")
    assert ok is True
    assert "mock" in msg.lower() or "ok" in msg.lower() or "connected" in msg.lower()


def test_test_connection_bad_prometheus(service):
    ok, msg = service.test_connection(mode="prometheus", prometheus_url="http://invalid:9999")
    assert ok is False


def test_run_analysis_mock(service):
    report = service.run_analysis(mode="mock", namespace="test-ns", top_n=5, seed=42)
    assert service.status == AnalysisStatus.DONE
    assert service.has_results
    assert report.namespace == "test-ns"
    # All 15 deployments are now analyzed (not just top N)
    assert report.analyzed_deployments == 15
    # Recommendations for every deployment with at least one resource to resize
    # (only those right-sized on both CPU and memory are skipped).
    assert len(report.recommendations) == 14


def test_get_report_after_analysis(service):
    service.run_analysis(mode="mock", namespace="test-ns", top_n=3, seed=42)
    report = service.get_report()
    assert report is not None
    assert report.analyzed_deployments == 15


def test_get_deployment_detail(service):
    service.run_analysis(mode="mock", namespace="test-ns", top_n=10, seed=42)
    report = service.get_report()
    name = report.profiles[0].name
    detail = service.get_deployment_detail(name)
    assert detail is not None
    assert detail.profile.name == name


def test_get_deployment_detail_not_found(service):
    service.run_analysis(mode="mock", namespace="test-ns", top_n=3, seed=42)
    detail = service.get_deployment_detail("nonexistent-deployment")
    assert detail is None


def test_get_timeseries_data(service):
    service.run_analysis(mode="mock", namespace="test-ns", top_n=5, seed=42)
    report = service.get_report()
    name = report.profiles[0].name
    ts = service.get_timeseries_data(name)
    assert "labels" in ts
    assert "cpu" in ts
    assert "memory" in ts
    assert len(ts["labels"]) > 0
    assert len(ts["cpu"]["usage"]) == len(ts["labels"])
    assert ts["cpu"]["request"] > 0
    assert ts["memory"]["request"] > 0


def test_get_timeseries_data_not_found(service):
    service.run_analysis(mode="mock", namespace="test-ns", top_n=3, seed=42)
    ts = service.get_timeseries_data("nonexistent")
    assert ts == {}


def test_get_all_patches(service):
    service.run_analysis(mode="mock", namespace="test-ns", top_n=5, seed=42)
    patches = service.get_all_patches()
    # Patches for every deployment with at least one resource to resize.
    assert len(patches) == 14
    for p in patches:
        assert "name" in p
        assert "yaml" in p
        assert "apiVersion" in p["yaml"]


def test_get_forecast(service):
    service.run_analysis(mode="mock", namespace="test-ns", seed=42)
    fc = service.get_forecast("log-aggregator")
    assert fc is not None
    assert fc.deployment_name == "log-aggregator"
    assert fc.cpu_forecast.trend.value in ("growing", "steady", "cyclic", "declining")


def test_get_forecast_not_found(service):
    service.run_analysis(mode="mock", namespace="test-ns", seed=42)
    fc = service.get_forecast("nonexistent")
    assert fc is None


def test_get_all_forecasts(service):
    service.run_analysis(mode="mock", namespace="test-ns", seed=42)
    forecasts = service.get_all_forecasts()
    assert len(forecasts) == 15


def test_get_at_risk_deployments(service):
    service.run_analysis(mode="mock", namespace="test-ns", seed=42)
    at_risk = service.get_at_risk_deployments()
    assert isinstance(at_risk, list)
    for fc in at_risk:
        assert fc.risk_level in ("critical", "warning")


# --- Multi-namespace ---


def test_multi_namespace_analysis(service):
    report = service.run_multi_namespace_analysis(
        namespaces=["ns1", "ns2"],
        mode="mock",
        seed=42,
    )
    assert service.status == AnalysisStatus.DONE
    assert service.has_results
    # Mock generates 15 per namespace, so 30 total
    assert report.analyzed_deployments == 30
    assert "ns1" in report.namespace
    assert "ns2" in report.namespace


def test_analyzed_namespaces_tracked(service):
    assert service.analyzed_namespaces == []
    service.run_analysis(mode="mock", namespace="alpha", seed=42)
    assert "alpha" in service.analyzed_namespaces
    service.run_analysis(mode="mock", namespace="beta", seed=42)
    assert "beta" in service.analyzed_namespaces


# --- Audit log integration ---


def test_service_has_audit_log(service):
    assert service.audit_log is not None


def test_audit_log_custom_path(tmp_path):
    svc = AnalysisService(audit_db_path=str(tmp_path / "custom_audit.db"))
    assert svc.audit_log is not None


# --- HPA conflicts ---


def test_deployment_detail_has_hpa_conflicts_field(service):
    service.run_analysis(mode="mock", namespace="test-ns", seed=42)
    report = service.get_report()
    name = report.profiles[0].name
    detail = service.get_deployment_detail(name)
    assert detail is not None
    # hpa_conflicts should be a list (empty in mock mode since no K8s cluster)
    assert isinstance(detail.hpa_conflicts, list)


def test_get_hpa_conflicts_no_recommendation(service):
    service.run_analysis(mode="mock", namespace="test-ns", seed=42)
    conflicts = service.get_hpa_conflicts("nonexistent")
    assert conflicts == []


# --- Last analysis params ---


def test_last_analysis_params_stored(service):
    assert service.last_analysis_params == {}
    service.run_analysis(mode="mock", namespace="test-ns", seed=42)
    params = service.last_analysis_params
    assert params["mode"] == "mock"
    assert params["namespace"] == "test-ns"
    assert params["seed"] == 42


def test_last_analysis_params_multi_namespace(service):
    service.run_multi_namespace_analysis(namespaces=["a", "b"], mode="mock", seed=42)
    params = service.last_analysis_params
    assert params["namespaces"] == ["a", "b"]
    assert params["mode"] == "mock"


# --- Multi-cloud costs ---


def test_get_multi_cloud_costs(service):
    service.run_analysis(mode="mock", namespace="test-ns", seed=42)
    multi = service.get_multi_cloud_costs()
    assert "aws" in multi
    assert "gcp" in multi
    assert "azure" in multi
    assert len(multi["aws"]) > 0
    # GCP should be cheapest
    gcp_total = sum(e.current_monthly_cost_usd for e in multi["gcp"])
    aws_total = sum(e.current_monthly_cost_usd for e in multi["aws"])
    assert gcp_total < aws_total


def test_get_multi_cloud_costs_empty(service):
    """Before analysis, multi-cloud costs returns empty dict."""
    assert service.get_multi_cloud_costs() == {}


# --- Namespace discovery ---


def test_get_available_namespaces_mock(service):
    """Mock mode returns demo-app as available namespace."""
    namespaces = service.get_available_namespaces(mode="mock")
    assert namespaces == ["demo-app"]


def test_get_available_namespaces_bad_mode(service):
    """Invalid mode returns empty list gracefully."""
    namespaces = service.get_available_namespaces(mode="bad-mode")
    assert namespaces == []
