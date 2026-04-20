"""Analyze command — identify over-provisioned deployments."""

from __future__ import annotations

import typer
from rich.console import Console

console = Console()


def analyze(
    namespace: str = typer.Option(..., "--namespace", "-n", help="Kubernetes namespace"),
    mode: str = typer.Option("prometheus", "--mode", "-m", help="Mode: prometheus, k8s, mock"),
    prometheus_url: str = typer.Option("", "--prometheus-url", "-p", help="Prometheus base URL"),
    db_path: str = typer.Option("", "--db-path", help="SQLite DB path (k8s mode)"),
    lookback: int = typer.Option(168, "--lookback", help="Lookback period in hours (default: 168)"),
    top: int = typer.Option(10, "--top", help="Number of top over-provisioned deployments"),
) -> None:
    """Analyze resource usage and identify over-provisioned deployments."""
    from kube_foresight.analyzer.profiler import profile_deployments, rank_by_over_provisioning
    from kube_foresight.cli.formatters import render_analysis_table
    from kube_foresight.collector import get_collector

    kwargs: dict = {}
    if mode == "prometheus" and not prometheus_url:
        console.print("[red]--prometheus-url is required for prometheus mode[/red]")
        raise typer.Exit(1)
    if mode == "k8s" and db_path:
        kwargs["db_path"] = db_path

    label = {"prometheus": "Prometheus", "k8s": "Kubernetes", "mock": "mock data"}.get(mode, mode)
    with console.status(f"[bold green]Connecting to {label}..."):
        collector = get_collector(
            mode=mode,
            prometheus_url=prometheus_url or None,
            **kwargs,
        )
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
