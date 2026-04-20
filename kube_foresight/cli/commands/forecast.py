"""Forecast command — predict resource trends and breach timelines."""

from __future__ import annotations

import typer
from rich.console import Console

console = Console()


def forecast(
    namespace: str = typer.Option(..., "--namespace", "-n", help="Kubernetes namespace"),
    mode: str = typer.Option("prometheus", "--mode", "-m", help="Mode: prometheus, k8s, mock"),
    prometheus_url: str = typer.Option("", "--prometheus-url", "-p", help="Prometheus base URL"),
    db_path: str = typer.Option("", "--db-path", help="SQLite DB path (k8s mode)"),
    lookback: int = typer.Option(168, "--lookback", help="Lookback period in hours"),
    forecast_days: int = typer.Option(30, "--forecast-days", help="Days to forecast ahead"),
) -> None:
    """Predict resource usage trends and days until request/limit breach."""
    from kube_foresight.cli.formatters import render_forecast_table
    from kube_foresight.collector import get_collector
    from kube_foresight.forecaster import generate_forecast

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

    with console.status("[bold green]Generating forecasts..."):
        seen: set[str] = set()
        forecasts = []
        for m in metrics:
            if m.deployment_name not in seen:
                seen.add(m.deployment_name)
                forecasts.append(generate_forecast(m, forecast_days=forecast_days))

    render_forecast_table(forecasts, console)
