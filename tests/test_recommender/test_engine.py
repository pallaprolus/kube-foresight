"""Tests for recommendation engine."""

from kube_foresight.analyzer.profiler import profile_deployments, rank_by_over_provisioning
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
