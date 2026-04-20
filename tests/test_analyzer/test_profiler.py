"""Tests for deployment profiling."""

from kube_foresight.analyzer.profiler import (
    classify_sizing,
    compute_over_provisioning_score,
    profile_deployments,
    rank_by_over_provisioning,
)
from kube_foresight.models import SizingCategory


def test_over_provisioning_score_fully_utilized():
    score = compute_over_provisioning_score(1.0, 1.0)
    assert score == 0.0


def test_over_provisioning_score_fully_wasted():
    score = compute_over_provisioning_score(0.0, 0.0)
    assert score == 1.0


def test_over_provisioning_score_partial():
    score = compute_over_provisioning_score(0.5, 0.5)
    assert score == 0.5  # 0.6*0.5 + 0.4*0.5 = 0.5


def test_over_provisioning_score_clamped():
    # Over-utilized should not go negative
    score = compute_over_provisioning_score(1.5, 1.5)
    assert score == 0.0


def test_profile_deployments(mock_metrics):
    profiles = profile_deployments(mock_metrics)
    assert len(profiles) == 15  # 15 deployments in mock
    for p in profiles:
        assert p.namespace == "test-ns"
        assert p.cpu_utilization_ratio > 0
        assert p.memory_utilization_ratio > 0


def test_rank_by_over_provisioning(mock_metrics):
    profiles = profile_deployments(mock_metrics)
    ranked = rank_by_over_provisioning(profiles, top_n=5)
    assert len(ranked) == 5
    # Should be sorted descending by score
    for i in range(len(ranked) - 1):
        assert ranked[i].over_provisioning_score >= ranked[i + 1].over_provisioning_score


def test_payment_processor_not_most_wasted(mock_metrics):
    """payment-processor is bursty but should not be the most over-provisioned."""
    profiles = profile_deployments(mock_metrics)
    ranked = rank_by_over_provisioning(profiles, top_n=15)
    pp_rank = next(i for i, p in enumerate(ranked) if p.name == "payment-processor")
    # Should not be in the top 3 most wasted (bursty but still uses resources)
    assert pp_rank > 2


def test_classify_sizing_under_provisioned():
    # CPU p95 > 80% of request → under-provisioned
    result = classify_sizing(cpu_p95=0.9, cpu_request=1.0, memory_p95=50.0, memory_request=100.0)
    assert result == SizingCategory.UNDER_PROVISIONED


def test_classify_sizing_under_provisioned_memory():
    # Memory p95 > 80% of request → under-provisioned
    result = classify_sizing(cpu_p95=0.1, cpu_request=1.0, memory_p95=90.0, memory_request=100.0)
    assert result == SizingCategory.UNDER_PROVISIONED


def test_classify_sizing_over_provisioned():
    # Both CPU and memory p95 < 30% of request → over-provisioned
    result = classify_sizing(cpu_p95=0.1, cpu_request=1.0, memory_p95=20.0, memory_request=100.0)
    assert result == SizingCategory.OVER_PROVISIONED


def test_classify_sizing_right_sized():
    # CPU p95 between 30-80%, memory p95 between 30-80%
    result = classify_sizing(cpu_p95=0.5, cpu_request=1.0, memory_p95=50.0, memory_request=100.0)
    assert result == SizingCategory.RIGHT_SIZED


def test_classify_sizing_right_sized_mixed():
    # CPU low but memory moderate → right-sized (not over-provisioned because memory > 30%)
    result = classify_sizing(cpu_p95=0.1, cpu_request=1.0, memory_p95=40.0, memory_request=100.0)
    assert result == SizingCategory.RIGHT_SIZED


def test_classify_sizing_zero_request():
    # Zero request → 0 ratio → over-provisioned
    result = classify_sizing(cpu_p95=0.0, cpu_request=0.0, memory_p95=0.0, memory_request=0.0)
    assert result == SizingCategory.OVER_PROVISIONED


def test_profile_deployments_sets_sizing_category(mock_metrics):
    profiles = profile_deployments(mock_metrics)
    categories = {p.sizing_category for p in profiles}
    # Mock data should have at least over-provisioned and right-sized
    assert SizingCategory.OVER_PROVISIONED in categories
    assert SizingCategory.RIGHT_SIZED in categories
