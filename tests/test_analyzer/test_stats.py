"""Tests for usage statistics computation."""

import pytest

from kube_foresight.analyzer.stats import (
    aggregate_deployment_metrics,
    compute_usage_stats,
    filter_anomalies,
)


def test_compute_usage_stats_basic():
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    stats = compute_usage_stats(values)
    assert stats.mean == 5.5
    assert stats.median == 5.5
    assert stats.min == 1.0
    assert stats.max == 10.0
    assert stats.sample_count == 10
    assert stats.p95 == pytest.approx(9.55, abs=0.1)
    assert stats.p99 == pytest.approx(9.91, abs=0.1)


def test_compute_usage_stats_uniform():
    values = [5.0] * 100
    stats = compute_usage_stats(values)
    assert stats.mean == 5.0
    assert stats.std_dev == 0.0
    assert stats.p95 == 5.0


def test_filter_anomalies_removes_outliers():
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 100.0]
    filtered = filter_anomalies(values)
    assert 100.0 not in filtered
    assert len(filtered) < len(values)


def test_filter_anomalies_preserves_normal_data():
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    filtered = filter_anomalies(values)
    assert filtered == values


def test_filter_anomalies_too_few_points():
    values = [1.0, 100.0, 200.0]
    filtered = filter_anomalies(values)
    assert filtered == values


def test_filter_anomalies_uniform_data():
    values = [5.0] * 10
    filtered = filter_anomalies(values)
    assert filtered == values


def test_compute_usage_stats_with_outlier():
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 1000.0]
    stats = compute_usage_stats(values)
    # The outlier (1000.0) should be filtered, so max should be ~10.0
    assert stats.max < 100


def test_aggregate_deployment_metrics(mock_metrics):
    grouped = aggregate_deployment_metrics(mock_metrics)
    assert "api-gateway" in grouped
    assert len(grouped["api-gateway"]) == 3  # 3 replicas
    assert len(grouped["notification-svc"]) == 1  # 1 replica
