"""Recommend command — generate right-sizing recommendations."""

from __future__ import annotations

import typer
from rich.console import Console

console = Console()


def recommend(
    namespace: str = typer.Option(..., "--namespace", "-n", help="Kubernetes namespace"),
    prometheus_url: str = typer.Option(..., "--prometheus-url", "-p", help="Prometheus base URL"),
    strategy: str = typer.Option("p95", "--strategy", "-s", help="Strategy: p95, p99, max"),
    headroom: float = typer.Option(0.20, "--headroom", help="Safety margin (0.0-1.0)"),
    lookback: int = typer.Option(168, "--lookback", help="Lookback period in hours"),
    top: int = typer.Option(10, "--top", help="Number of top over-provisioned deployments"),
    cloud_provider: str = typer.Option(
        "aws", "--cloud-provider",
        help="Cloud provider: aws, gcp, azure",
    ),
) -> None:
    """Generate right-sizing recommendations with confidence levels."""
    from kube_foresight.analyzer.profiler import profile_deployments, rank_by_over_provisioning
    from kube_foresight.cli.formatters import render_cost_summary, render_recommendations_table
    from kube_foresight.collector import get_collector
    from kube_foresight.pricing.estimator import estimate_namespace_costs
    from kube_foresight.pricing.providers import get_provider
    from kube_foresight.recommender.engine import generate_recommendations

    with console.status("[bold green]Connecting to Prometheus..."):
        collector = get_collector(mode="prometheus", prometheus_url=prometheus_url)
        ok, msg = collector.check_connection()
        if not ok:
            console.print(f"[red]Connection failed: {msg}[/red]")
            raise typer.Exit(1)
        console.print(f"[green]{msg}[/green]")

    with console.status("[bold green]Collecting metrics..."):
        metrics = collector.collect(namespace=namespace, lookback_hours=lookback)

    if not metrics:
        console.print(f"[yellow]No metrics found for namespace '{namespace}'[/yellow]")
        raise typer.Exit(0)

    profiles = profile_deployments(metrics)
    ranked = rank_by_over_provisioning(profiles, top_n=top)

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
