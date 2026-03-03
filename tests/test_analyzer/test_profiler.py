"""Tests for deployment profiling."""

from kube_foresight.analyzer.profiler import (
    compute_over_provisioning_score,
    profile_deployments,
    rank_by_over_provisioning,
)


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
