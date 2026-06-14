"""Backtest kube-foresight recommendations against a held-out future window.

Methodology (the standard right-sizing evaluation, cf. VPA / Google Autopilot):

1. Split each container's usage chronologically into a *train* window (the
   first ``train_fraction``) and a *test* window (the remainder).
2. Generate recommendations from the train window only.
3. Score them on the test window:
     - violation rate = fraction of held-out samples that EXCEED the
       recommended request (request breach → contention/throttling) or limit
       (limit breach → OOM kill for memory). Lower is safer.
     - savings %      = how much the recommendation shrinks the request.
   A good tool achieves high savings with low violations; both are reported
   together because the trade-off between them is the point.

Run ``python -m benchmarks.backtest --help``.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field

import numpy as np

from kube_foresight.analyzer.profiler import profile_deployments
from kube_foresight.models import ContainerMetrics
from kube_foresight.recommender.engine import generate_recommendations


@dataclass
class DeploymentResult:
    deployment: str
    n_replicas: int
    n_test_samples: int
    cpu_req_violation: float
    cpu_limit_violation: float
    mem_req_violation: float
    mem_limit_violation: float
    cpu_savings_pct: float
    mem_savings_pct: float


@dataclass
class StrategyResult:
    strategy: str
    headroom: float
    n_deployments: int
    n_recommended: int
    median_cpu_req_violation: float
    p90_cpu_req_violation: float
    median_mem_limit_violation: float
    p90_mem_limit_violation: float
    median_cpu_savings: float
    median_mem_savings: float
    n_unsafe: int
    violation_threshold: float
    results: list[DeploymentResult] = field(default_factory=list)


def split_metrics(
    metrics: list[ContainerMetrics], train_fraction: float
) -> tuple[list[ContainerMetrics], dict[str, tuple[np.ndarray, np.ndarray]]]:
    """Split each container at ``train_fraction`` of its own time span.

    Returns (train ContainerMetrics, deployment → (test cpu samples,
    test mem samples) pooled across that deployment's replicas).
    """
    train: list[ContainerMetrics] = []
    test_cpu: dict[str, list[float]] = {}
    test_mem: dict[str, list[float]] = {}

    for cm in metrics:
        if not cm.cpu_usage or not cm.memory_usage:
            continue
        t0 = cm.cpu_usage[0][0]
        t1 = cm.cpu_usage[-1][0]
        split_ts = t0 + (t1 - t0) * train_fraction

        cpu_train = [(t, v) for t, v in cm.cpu_usage if t <= split_ts]
        mem_train = [(t, v) for t, v in cm.memory_usage if t <= split_ts]
        cpu_test = [v for t, v in cm.cpu_usage if t > split_ts]
        mem_test = [v for t, v in cm.memory_usage if t > split_ts]
        if not cpu_train or not cpu_test:
            continue

        train.append(
            ContainerMetrics(
                container_name=cm.container_name,
                pod_name=cm.pod_name,
                deployment_name=cm.deployment_name,
                namespace=cm.namespace,
                cpu_usage=cpu_train,
                memory_usage=mem_train,
                cpu_spec=cm.cpu_spec,
                memory_spec=cm.memory_spec,
            )
        )
        test_cpu.setdefault(cm.deployment_name, []).extend(cpu_test)
        test_mem.setdefault(cm.deployment_name, []).extend(mem_test)

    pooled = {
        name: (np.array(test_cpu[name]), np.array(test_mem.get(name, [])))
        for name in test_cpu
    }
    return train, pooled


def score_strategy(
    train: list[ContainerMetrics],
    test_pool: dict[str, tuple[np.ndarray, np.ndarray]],
    strategy: str,
    headroom: float,
    violation_threshold: float,
) -> StrategyResult:
    profiles = profile_deployments(train)
    recs = generate_recommendations(profiles, strategy=strategy, headroom=headroom)

    results: list[DeploymentResult] = []
    for rec in recs:
        cpu_test, mem_test = test_pool.get(rec.deployment_name, (np.array([]), np.array([])))
        if cpu_test.size == 0:
            continue
        cpu_req_v = float(np.mean(cpu_test > rec.recommended_cpu_request))
        cpu_lim_v = float(np.mean(cpu_test > rec.recommended_cpu_limit))
        mem_req_v = (
            float(np.mean(mem_test > rec.recommended_memory_request))
            if mem_test.size
            else 0.0
        )
        mem_lim_v = (
            float(np.mean(mem_test > rec.recommended_memory_limit))
            if mem_test.size
            else 0.0
        )
        results.append(
            DeploymentResult(
                deployment=rec.deployment_name,
                n_replicas=next(
                    (p.replica_count for p in profiles if p.name == rec.deployment_name), 1
                ),
                n_test_samples=int(cpu_test.size),
                cpu_req_violation=cpu_req_v,
                cpu_limit_violation=cpu_lim_v,
                mem_req_violation=mem_req_v,
                mem_limit_violation=mem_lim_v,
                cpu_savings_pct=rec.cpu_reduction_pct,
                mem_savings_pct=rec.memory_reduction_pct,
            )
        )

    def _median(vals: list[float]) -> float:
        return float(np.median(vals)) if vals else 0.0

    def _p90(vals: list[float]) -> float:
        return float(np.percentile(vals, 90)) if vals else 0.0

    cpu_req_v = [r.cpu_req_violation for r in results]
    mem_lim_v = [r.mem_limit_violation for r in results]
    n_unsafe = sum(
        1
        for r in results
        if r.cpu_req_violation > violation_threshold
        or r.mem_limit_violation > violation_threshold
    )

    return StrategyResult(
        strategy=strategy,
        headroom=headroom,
        n_deployments=len(test_pool),
        n_recommended=len(results),
        median_cpu_req_violation=_median(cpu_req_v),
        p90_cpu_req_violation=_p90(cpu_req_v),
        median_mem_limit_violation=_median(mem_lim_v),
        p90_mem_limit_violation=_p90(mem_lim_v),
        median_cpu_savings=_median([r.cpu_savings_pct for r in results]),
        median_mem_savings=_median([r.mem_savings_pct for r in results]),
        n_unsafe=n_unsafe,
        violation_threshold=violation_threshold,
        results=results,
    )


def run_backtest(
    metrics: list[ContainerMetrics],
    *,
    strategies: list[str],
    headroom: float,
    train_fraction: float,
    violation_threshold: float,
) -> list[StrategyResult]:
    train, test_pool = split_metrics(metrics, train_fraction)
    return [
        score_strategy(train, test_pool, s, headroom, violation_threshold) for s in strategies
    ]


def print_report(results: list[StrategyResult]) -> None:
    from rich.console import Console
    from rich.table import Table

    console = Console()
    first = results[0]
    console.print(
        f"\n[bold]Backtest[/bold] — {first.n_deployments} deployments, "
        f"headroom {first.headroom:.0%}, "
        f"unsafe if violation > {first.violation_threshold:.0%}\n"
    )

    table = Table(show_header=True, header_style="bold")
    table.add_column("Strategy")
    table.add_column("Recs", justify="right")
    table.add_column("CPU savings\n(median)", justify="right")
    table.add_column("Mem savings\n(median)", justify="right")
    table.add_column("CPU req viol.\nmedian / p90", justify="right")
    table.add_column("Mem OOM viol.\nmedian / p90", justify="right")
    table.add_column("Unsafe", justify="right")

    for r in results:
        unsafe_style = "red" if r.n_unsafe else "green"
        table.add_row(
            r.strategy,
            f"{r.n_recommended}/{r.n_deployments}",
            f"{r.median_cpu_savings:.0f}%",
            f"{r.median_mem_savings:.0f}%",
            f"{r.median_cpu_req_violation:.1%} / {r.p90_cpu_req_violation:.1%}",
            f"{r.median_mem_limit_violation:.1%} / {r.p90_mem_limit_violation:.1%}",
            f"[{unsafe_style}]{r.n_unsafe}[/{unsafe_style}]",
        )
    console.print(table)
    console.print(
        "\n[dim]Lower violation = safer; higher savings = more value. "
        "The right strategy maximizes savings while keeping violations near zero.[/dim]\n"
    )


def _load_metrics(args: argparse.Namespace) -> list[ContainerMetrics]:
    if args.source == "mock":
        from kube_foresight.collector.mock import MockCollector

        return MockCollector(seed=42).collect(lookback_hours=args.lookback)

    from benchmarks.alibaba import load_alibaba_trace

    return load_alibaba_trace(
        args.trace_dir,
        max_app_groups=args.max_app_groups,
        machine_mem_gib=args.machine_mem_gib,
        max_usage_rows=args.max_usage_rows,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        choices=["alibaba", "mock"],
        default="alibaba",
        help="Trace source. 'mock' runs the synthetic generator for a quick self-test.",
    )
    parser.add_argument("--trace-dir", help="Directory with the Alibaba v2018 CSVs.")
    parser.add_argument("--train-fraction", type=float, default=0.7)
    parser.add_argument("--headroom", type=float, default=0.20)
    parser.add_argument("--violation-threshold", type=float, default=0.05)
    parser.add_argument(
        "--strategies", default="p95,p99,max", help="Comma-separated strategies to compare."
    )
    parser.add_argument("--max-app-groups", type=int, default=200)
    parser.add_argument("--machine-mem-gib", type=float, default=96.0)
    parser.add_argument("--max-usage-rows", type=int, default=None)
    parser.add_argument("--lookback", type=int, default=168, help="Mock source: hours.")
    args = parser.parse_args(argv)

    if args.source == "alibaba" and not args.trace_dir:
        parser.error("--trace-dir is required for --source alibaba (see benchmarks/README.md)")

    metrics = _load_metrics(args)
    if not metrics:
        print("No usable container metrics loaded.")
        return 1

    results = run_backtest(
        metrics,
        strategies=[s.strip() for s in args.strategies.split(",") if s.strip()],
        headroom=args.headroom,
        train_fraction=args.train_fraction,
        violation_threshold=args.violation_threshold,
    )
    print_report(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
