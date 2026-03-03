"""Analyze command — identify over-provisioned deployments."""

from __future__ import annotations

import typer
from rich.console import Console

console = Console()


def analyze(
    namespace: str = typer.Option(..., "--namespace", "-n", help="Kubernetes namespace"),
    prometheus_url: str = typer.Option(..., "--prometheus-url", "-p", help="Prometheus base URL"),
    lookback: int = typer.Option(168, "--lookback", help="Lookback period in hours (default: 168)"),
    top: int = typer.Option(10, "--top", help="Number of top over-provisioned deployments"),
) -> None:
    """Analyze resource usage and identify over-provisioned deployments."""
    from kube_foresight.analyzer.profiler import profile_deployments, rank_by_over_provisioning
    from kube_foresight.cli.formatters import render_analysis_table
    from kube_foresight.collector import get_collector

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

    render_analysis_table(ranked, console)
