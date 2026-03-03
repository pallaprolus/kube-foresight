"""Tests for mock collector."""

from kube_foresight.collector.mock import DEPLOYMENT_PROFILES, MockCollector


def test_check_connection():
    collector = MockCollector()
    ok, msg = collector.check_connection()
    assert ok is True
    assert "Mock" in msg


def test_collect_returns_all_deployments(mock_metrics):
    deployment_names = {m.deployment_name for m in mock_metrics}
    assert deployment_names == set(DEPLOYMENT_PROFILES.keys())


def test_collect_correct_replica_count(mock_metrics):
    """Each deployment should have the expected number of containers (replicas)."""
    from collections import Counter
    counts = Counter(m.deployment_name for m in mock_metrics)
    for name, (_, _, _, _, _, replicas) in DEPLOYMENT_PROFILES.items():
        assert counts[name] == replicas, f"{name}: expected {replicas}, got {counts[name]}"


def test_collect_timeseries_length(mock_metrics):
    """Default 7 days at 5min intervals = 2016 points."""
    for m in mock_metrics:
        assert len(m.cpu_usage) == 2016
        assert len(m.memory_usage) == 2016


def test_collect_values_non_negative(mock_metrics):
    for m in mock_metrics:
        for _, val in m.cpu_usage:
            assert val >= 0, f"Negative CPU value for {m.pod_name}"
        for _, val in m.memory_usage:
            assert val >= 0, f"Negative memory value for {m.pod_name}"


def test_collect_specs_match_profiles(mock_metrics):
    for m in mock_metrics:
        profile = DEPLOYMENT_PROFILES[m.deployment_name]
        cpu_req, mem_req = profile[0], profile[1]
        assert m.cpu_spec.request == cpu_req
        assert m.memory_spec.request == mem_req
        assert m.cpu_spec.limit == cpu_req * 2
        assert m.memory_spec.limit == mem_req * 2


def test_collect_namespace(mock_metrics):
    for m in mock_metrics:
        assert m.namespace == "test-ns"


def test_reproducibility():
    """Same seed should produce identical results."""
    c1 = MockCollector(seed=123)
    c2 = MockCollector(seed=123)
    m1 = c1.collect(namespace="ns")
    m2 = c2.collect(namespace="ns")
    for a, b in zip(m1, m2):
        assert [v for _, v in a.cpu_usage] == [v for _, v in b.cpu_usage]
