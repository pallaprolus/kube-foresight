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
    assert report.analyzed_deployments == 5
    assert len(report.recommendations) == 5


def test_get_report_after_analysis(service):
    service.run_analysis(mode="mock", namespace="test-ns", top_n=3, seed=42)
    report = service.get_report()
    assert report is not None
    assert report.analyzed_deployments == 3


def test_get_deployment_detail(service):
    service.run_analysis(mode="mock", namespace="test-ns", top_n=10, seed=42)
    report = service.get_report()
    name = report.profiles[0].name
    detail = service.get_deployment_detail(name)
    assert detail is not None
    assert detail.profile.name == name
    assert detail.recommendation is not None
    assert detail.cost_estimate is not None
    assert detail.patch_yaml is not None
    assert "apiVersion" in detail.patch_yaml


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
    assert len(patches) == 5
    for p in patches:
        assert "name" in p
        assert "yaml" in p
        assert "apiVersion" in p["yaml"]
