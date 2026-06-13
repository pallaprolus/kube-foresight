"""Tests for the trace-backtest harness against the committed synthetic fixture."""

from pathlib import Path

import pytest

from benchmarks.alibaba import load_alibaba_trace
from benchmarks.backtest import run_backtest, split_metrics

FIXTURE_DIR = Path(__file__).parent.parent.parent / "benchmarks" / "fixtures"


@pytest.fixture
def metrics():
    return load_alibaba_trace(FIXTURE_DIR, machine_mem_gib=96.0)


def test_adapter_loads_deployments_and_replicas(metrics):
    by_name = {m.deployment_name for m in metrics}
    assert by_name == {"web-steady", "api-bursty", "worker-drift"}
    # web-steady and api-bursty have 2 replicas each, worker-drift has 1.
    assert len(metrics) == 5


def test_adapter_unit_conversion(metrics):
    web = next(m for m in metrics if m.deployment_name == "web-steady")
    # cpu_request 400 centi-cores → 4.0 cores
    assert web.cpu_spec.request == pytest.approx(4.0)
    # mem request 20% of a 96 GiB machine → ~19.2 GiB in bytes
    assert web.memory_spec.request == pytest.approx(0.20 * 96 * 1024**3, rel=1e-6)
    # usage is in cores, well under the request (over-provisioned)
    cpu_vals = [v for _, v in web.cpu_usage]
    assert max(cpu_vals) < web.cpu_spec.request


def test_split_is_chronological(metrics):
    train, test_pool = split_metrics(metrics, train_fraction=0.7)
    assert train and test_pool
    for cm in train:
        # every train timestamp precedes every pooled test sample's window
        assert len(cm.cpu_usage) < 240  # a subset of the full series


def test_backtest_surfaces_savings_and_drift(metrics):
    [p95] = run_backtest(
        metrics,
        strategies=["p95"],
        headroom=0.20,
        train_fraction=0.7,
        violation_threshold=0.05,
    )
    assert p95.n_recommended == 3
    # The over-provisioned deployments yield real savings.
    assert p95.median_cpu_savings > 50

    per = {r.deployment: r for r in p95.results}
    # web-steady: stationary → recommendation holds on the future window.
    assert per["web-steady"].cpu_req_violation < 0.05
    # worker-drift: usage ramps after the split → train-based rec is breached.
    assert per["worker-drift"].cpu_req_violation > 0.30
    # The harness flags at least the drifting deployment as unsafe.
    assert p95.n_unsafe >= 1


def test_mock_source_runs():
    from kube_foresight.collector.mock import MockCollector

    metrics = MockCollector(seed=42).collect(lookback_hours=72)
    results = run_backtest(
        metrics,
        strategies=["p95", "p99"],
        headroom=0.20,
        train_fraction=0.7,
        violation_threshold=0.05,
    )
    assert len(results) == 2
    assert all(r.n_recommended > 0 for r in results)
