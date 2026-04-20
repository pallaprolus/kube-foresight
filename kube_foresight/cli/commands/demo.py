"""Demo command — runs full pipeline with synthetic data."""

from __future__ import annotations

import typer
from rich.console import Console

console = Console()


def demo(
    top: int = typer.Option(10, "--top", help="Number of top over-provisioned deployments"),
    strategy: str = typer.Option("p95", "--strategy", "-s", help="Strategy: p95, p99, max"),
    headroom: float = typer.Option(0.20, "--headroom", help="Safety margin (0.0-1.0)"),
    seed: int = typer.Option(42, "--seed", help="Random seed for reproducibility"),
    output_dir: str | None = typer.Option(
        None, "--output-dir", "-o", help="Write YAML patches to this directory"
    ),
    cloud_provider: str = typer.Option(
        "aws", "--cloud-provider",
        help="Cloud provider: aws, gcp, azure",
    ),
) -> None:
    """Run full analysis with synthetic data (no Prometheus needed)."""
    from kube_foresight.analyzer.profiler import profile_deployments, rank_by_over_provisioning
    from kube_foresight.cli.formatters import (
        render_analysis_table,
        render_cost_summary,
        render_patch_summary,
        render_recommendations_table,
    )
    from kube_foresight.collector import get_collector
    from kube_foresight.pricing.estimator import estimate_namespace_costs
    from kube_foresight.pricing.providers import get_provider
    from kube_foresight.recommender.engine import generate_recommendations
    from kube_foresight.recommender.patch import write_patches

    console.print("[bold]kube-foresight demo[/bold] — synthetic workload analysis\n")

    with console.status("[bold green]Generating synthetic metrics..."):
        collector = get_collector(mode="mock", seed=seed)
        metrics = collector.collect(namespace="demo-app")

    console.print(
        f"[green]Collected metrics for {len(metrics)} containers "
        f"across {len({m.deployment_name for m in metrics})} deployments[/green]"
    )

    profiles = profile_deployments(metrics)
    ranked = rank_by_over_provisioning(profiles, top_n=top)

    render_analysis_table(ranked, console)

    recommendations = generate_recommendations(ranked, strategy=strategy, headroom=headroom)
    render_recommendations_table(recommendations, console)

    provider = get_provider(cloud_provider)
    estimates = estimate_namespace_costs(ranked, recommendations, provider=provider)
    total_monthly = sum(e.monthly_savings_usd for e in estimates)
    total_annual = sum(e.annual_savings_usd for e in estimates)
    render_cost_summary(
        estimates, total_monthly, total_annual, console,
        provider_name=provider.provider_name(),
    )

    if output_dir:
        patch_files = write_patches(recommendations, output_dir=output_dir)
        render_patch_summary(patch_files, console)
