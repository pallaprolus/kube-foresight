"""Patch command — generate right-sizing YAML patches."""

from __future__ import annotations

import typer
from rich.console import Console

console = Console()


def patch(
    namespace: str = typer.Option(..., "--namespace", "-n", help="Kubernetes namespace"),
    mode: str = typer.Option("prometheus", "--mode", "-m", help="Mode: prometheus, k8s, mock"),
    prometheus_url: str = typer.Option("", "--prometheus-url", "-p", help="Prometheus base URL"),
    db_path: str = typer.Option("", "--db-path", help="SQLite DB path (k8s mode)"),
    strategy: str = typer.Option("p95", "--strategy", "-s", help="Strategy: p95, p99, max"),
    headroom: float = typer.Option(0.20, "--headroom", help="Safety margin (0.0-1.0)"),
    lookback: int = typer.Option(168, "--lookback", help="Lookback period in hours"),
    top: int = typer.Option(10, "--top", help="Number of top over-provisioned deployments"),
    output_dir: str = typer.Option("./patches", "--output-dir", "-o", help="Output directory"),
) -> None:
    """Generate right-sizing YAML patches for kubectl apply."""
    from kube_foresight.analyzer.profiler import profile_deployments, rank_by_over_provisioning
    from kube_foresight.cli.formatters import render_patch_summary
    from kube_foresight.collector import get_collector
    from kube_foresight.recommender.engine import generate_recommendations
    from kube_foresight.recommender.patch import write_patches

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

    recommendations = generate_recommendations(ranked, strategy=strategy, headroom=headroom)
    patch_files = write_patches(recommendations, output_dir=output_dir)
    render_patch_summary(patch_files, console)
