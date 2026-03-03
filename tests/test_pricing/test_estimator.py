"""Tests for cost estimation."""

from kube_foresight.analyzer.profiler import profile_deployments, rank_by_over_provisioning
from kube_foresight.models import (
    ConfidenceLevel,
    DeploymentProfile,
    Recommendation,
    ResourceSpec,
    UsageStats,
)
from kube_foresight.pricing.estimator import HOURS_PER_MONTH, estimate_cost, estimate_namespace_costs
from kube_foresight.pricing.providers.aws import AWSPricingProvider
from kube_foresight.recommender.engine import generate_recommendations


def _make_profile():
    stats = UsageStats(
        mean=0.1, median=0.09, p95=0.15, p99=0.18,
        max=0.2, min=0.01, std_dev=0.03, sample_count=2016,
    )
    return DeploymentProfile(
        name="test-app",
        container_name="app",
        namespace="default",
        replica_count=2,
        cpu_stats=stats,
        memory_stats=stats,
        cpu_spec=ResourceSpec(request=1.0, limit=2.0),
        memory_spec=ResourceSpec(request=1024 * 1024 * 1024, limit=2 * 1024 * 1024 * 1024),
        cpu_utilization_ratio=0.1,
        memory_utilization_ratio=0.1,
        over_provisioning_score=0.9,
    )


def _make_recommendation():
    return Recommendation(
        deployment_name="test-app",
        container_name="app",
        namespace="default",
        strategy="p95",
        headroom=0.2,
        current_cpu_request=1.0,
        current_cpu_limit=2.0,
        current_memory_request=1024 * 1024 * 1024,
        current_memory_limit=2 * 1024 * 1024 * 1024,
        recommended_cpu_request=0.2,
        recommended_cpu_limit=0.3,
        recommended_memory_request=256 * 1024 * 1024,
        recommended_memory_limit=384 * 1024 * 1024,
        cpu_reduction_pct=80.0,
        memory_reduction_pct=75.0,
        confidence=ConfidenceLevel.HIGH,
    )


def test_estimate_cost_savings_positive():
    profile = _make_profile()
    rec = _make_recommendation()
    est = estimate_cost(profile, rec)
    assert est.monthly_savings_usd > 0
    assert abs(est.annual_savings_usd - est.monthly_savings_usd * 12) < 1.0
    assert est.recommended_monthly_cost_usd < est.current_monthly_cost_usd


def test_estimate_cost_uses_replicas():
    profile = _make_profile()
    rec = _make_recommendation()
    est = estimate_cost(profile, rec)

    # Current cost = (1.0 * 0.04048 + 1.0 * 0.004445) * 730 * 2
    provider = AWSPricingProvider()
    expected_current = (
        1.0 * provider.cpu_cost_per_hour()
        + 1.0 * provider.memory_cost_per_hour_gib()
    ) * HOURS_PER_MONTH * 2
    assert abs(est.current_monthly_cost_usd - round(expected_current, 2)) < 0.01


def test_estimate_namespace_costs_full_pipeline(mock_metrics):
    profiles = profile_deployments(mock_metrics)
    ranked = rank_by_over_provisioning(profiles, top_n=5)
    recs = generate_recommendations(ranked)
    estimates = estimate_namespace_costs(ranked, recs)

    assert len(estimates) == 5
    total = sum(e.monthly_savings_usd for e in estimates)
    assert total > 0
