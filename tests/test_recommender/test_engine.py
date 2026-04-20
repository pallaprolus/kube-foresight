"""Tests for recommendation engine."""

from kube_foresight.analyzer.profiler import profile_deployments, rank_by_over_provisioning
from kube_foresight.models import (
    DeploymentProfile,
    ResourceSpec,
    SizingCategory,
    UsageStats,
)
from kube_foresight.recommender.engine import generate_recommendations


def test_generate_recommendations(mock_metrics):
    profiles = profile_deployments(mock_metrics)
    ranked = rank_by_over_provisioning(profiles, top_n=5)
    recs = generate_recommendations(ranked)

    assert len(recs) == 5
    for rec in recs:
        assert rec.recommended_cpu_request <= rec.current_cpu_request
        assert rec.recommended_memory_request <= rec.current_memory_request
        assert rec.cpu_reduction_pct >= 0
        assert rec.memory_reduction_pct >= 0
        assert rec.strategy == "p95"
        assert rec.headroom == 0.20


def test_recommendations_have_confidence(mock_metrics):
    profiles = profile_deployments(mock_metrics)
    ranked = rank_by_over_provisioning(profiles, top_n=3)
    recs = generate_recommendations(ranked)

    for rec in recs:
        assert rec.confidence.value in ("high", "medium", "low")


def test_right_sized_deployments_skipped():
    """Right-sized deployments should not get recommendations."""
    profile = DeploymentProfile(
        name="healthy-app",
        container_name="app",
        namespace="default",
        replica_count=2,
        cpu_stats=UsageStats(
            mean=0.5, median=0.5, p95=0.6, p99=0.7,
            max=0.8, min=0.1, std_dev=0.1, sample_count=2016,
        ),
        memory_stats=UsageStats(
            mean=300e6, median=300e6, p95=400e6, p99=450e6,
            max=500e6, min=100e6, std_dev=50e6, sample_count=2016,
        ),
        cpu_spec=ResourceSpec(request=1.0, limit=2.0),
        memory_spec=ResourceSpec(request=512 * 1024 * 1024, limit=1024 * 1024 * 1024),
        cpu_utilization_ratio=0.5,
        memory_utilization_ratio=0.56,
        over_provisioning_score=0.2,
        sizing_category=SizingCategory.RIGHT_SIZED,
    )
    recs = generate_recommendations([profile])
    assert len(recs) == 0


def test_under_provisioned_recommends_increase():
    """Under-provisioned deployments should get upward recommendations."""
    profile = DeploymentProfile(
        name="busy-app",
        container_name="app",
        namespace="default",
        replica_count=1,
        cpu_stats=UsageStats(
            mean=0.9, median=0.85, p95=0.95, p99=0.98,
            max=1.0, min=0.5, std_dev=0.1, sample_count=2016,
        ),
        memory_stats=UsageStats(
            mean=900e6, median=850e6, p95=950e6, p99=980e6,
            max=1e9, min=500e6, std_dev=100e6, sample_count=2016,
        ),
        cpu_spec=ResourceSpec(request=1.0, limit=1.5),
        memory_spec=ResourceSpec(request=1024 * 1024 * 1024, limit=2 * 1024 * 1024 * 1024),
        cpu_utilization_ratio=0.9,
        memory_utilization_ratio=0.84,
        over_provisioning_score=0.0,
        sizing_category=SizingCategory.UNDER_PROVISIONED,
    )
    recs = generate_recommendations([profile])
    assert len(recs) == 1
    rec = recs[0]
    # Should recommend increasing resources
    assert rec.recommended_cpu_request >= rec.current_cpu_request
    # Negative reduction = increase
    assert rec.cpu_reduction_pct <= 0
