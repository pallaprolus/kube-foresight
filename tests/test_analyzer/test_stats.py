"""Tests for usage statistics computation."""

import pytest

from kube_foresight.analyzer.stats import (
    aggregate_deployment_metrics,
    compute_usage_stats,
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


def test_compute_usage_stats_preserves_demand_spikes():
    """Usage spikes must NOT be filtered out — they are what we size for.

    Discarding the upper tail would cause under-provisioning (throttling /
    OOM kills), so a real spike has to be reflected in max and the high
    percentiles.
    """
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 1000.0]
    stats = compute_usage_stats(values)
    assert stats.max == 1000.0
    # The single large spike sits in the top 1%, so p99 picks it up.
    assert stats.p99 > 100


def test_compute_usage_stats_spike_raises_variability():
    """A spike must increase std_dev (and thus CV) so confidence isn't inflated."""
    steady = compute_usage_stats([5.0] * 50)
    with_spike = compute_usage_stats([5.0] * 49 + [500.0])
    assert with_spike.std_dev > steady.std_dev


def test_aggregate_deployment_metrics(mock_metrics):
    grouped = aggregate_deployment_metrics(mock_metrics)
    assert "api-gateway" in grouped
    assert len(grouped["api-gateway"]) == 3  # 3 replicas
    assert len(grouped["notification-svc"]) == 1  # 1 replica
