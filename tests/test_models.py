"""Tests for domain models."""

from kube_foresight.models import (
    ConfidenceLevel,
    CostEstimate,
    ResourceSpec,
    UsageStats,
)


def test_resource_spec():
    spec = ResourceSpec(request=0.5, limit=1.0)
    assert spec.request == 0.5
    assert spec.limit == 1.0


def test_usage_stats():
    stats = UsageStats(
        mean=0.1, median=0.09, p95=0.15, p99=0.18, max=0.2, min=0.01, std_dev=0.03,
        sample_count=2016,
    )
    assert stats.p95 == 0.15
    assert stats.sample_count == 2016


def test_confidence_level_values():
    assert ConfidenceLevel.HIGH.value == "high"
    assert ConfidenceLevel.MEDIUM.value == "medium"
    assert ConfidenceLevel.LOW.value == "low"


def test_cost_estimate():
    est = CostEstimate(
        deployment_name="test",
        namespace="ns",
        replica_count=2,
        current_monthly_cost_usd=100.0,
        recommended_monthly_cost_usd=40.0,
        monthly_savings_usd=60.0,
        annual_savings_usd=720.0,
    )
    assert est.monthly_savings_usd == 60.0
    assert est.annual_savings_usd == 720.0
