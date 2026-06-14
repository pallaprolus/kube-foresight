"""Dashboard command: launch the kube-foresight web UI."""

from __future__ import annotations

import os

import typer
from rich.console import Console

console = Console()


def dashboard(
    port: int = typer.Option(8080, "--port", "-p", help="Port to listen on"),
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind to"),
    demo: bool = typer.Option(False, "--demo", "-d", help="Pre-load demo analysis results"),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload for development"),
    # Scheduler options
    continuous: bool = typer.Option(
        False, "--continuous", "-c",
        help="Enable background collection & analysis",
    ),
    namespaces: str = typer.Option(
        "default", "--namespaces", "-n",
        help="Comma-separated namespaces to monitor",
    ),
    mode: str = typer.Option("k8s", "--mode", "-m", help="Collector mode: mock, k8s, prometheus"),
    db_path: str = typer.Option("", "--db-path", help="SQLite database path for k8s metrics"),
    collect_interval: int = typer.Option(
        300, "--collect-interval",
        help="Seconds between metric collections",
    ),
    analysis_interval: int = typer.Option(
        900, "--analysis-interval",
        help="Seconds between analysis runs",
    ),
    prometheus_url: str = typer.Option("", "--prometheus-url", help="Prometheus server URL"),
    # Alerting
    webhook_url: str = typer.Option("", "--webhook-url", help="Generic webhook URL for alerts"),
    slack_webhook_url: str = typer.Option(
        "", "--slack-webhook-url",
        help="Slack incoming webhook URL",
    ),
) -> None:
    """Launch the kube-foresight web dashboard."""
    try:
        import uvicorn  # noqa: F401
    except ImportError:
        console.print(
            "[red]Dashboard dependencies not installed.[/red]\n"
            'Run: [bold]pip install -e ".[dashboard]"[/bold]'
        )
        raise typer.Exit(1)

    # Always expose CLI flags as env vars so the dashboard form
    # can pre-fill data source, DB path, and namespace defaults.
    os.environ.setdefault("KF_MODE", mode)
    os.environ.setdefault("KF_NAMESPACES", namespaces)
    if db_path:
        os.environ.setdefault("KF_DB_PATH", db_path)
    if prometheus_url:
        os.environ.setdefault("KF_PROMETHEUS_URL", prometheus_url)

    # Scheduler + alerting env vars (only when continuous mode)
    if continuous:
        os.environ["KF_SCHEDULER_ENABLED"] = "true"
        os.environ["KF_MODE"] = mode
        os.environ["KF_NAMESPACES"] = namespaces
        os.environ["KF_COLLECT_INTERVAL"] = str(collect_interval)
        os.environ["KF_ANALYSIS_INTERVAL"] = str(analysis_interval)
        if db_path:
            os.environ["KF_DB_PATH"] = db_path
        if prometheus_url:
            os.environ["KF_PROMETHEUS_URL"] = prometheus_url
        if webhook_url:
            os.environ["KF_WEBHOOK_URL"] = webhook_url
        if slack_webhook_url:
            os.environ["KF_SLACK_WEBHOOK_URL"] = slack_webhook_url

    from kube_foresight.dashboard import create_app

    app = create_app()

    if demo:
        # Pre-run analysis with mock data so the dashboard loads with results
        console.print("[blue]Running demo analysis...[/blue]")
        service = app.state.analysis_service
        service.run_analysis(
            mode="mock",
            namespace="demo-app",
            lookback_hours=168,
            strategy="p99",
            headroom=0.20,
            top_n=10,
            seed=42,
        )
        console.print("[green]Demo data loaded.[/green]")

    if continuous:
        console.print(
            f"[blue]Continuous mode:[/blue] collecting every {collect_interval}s, "
            f"analyzing every {analysis_interval}s"
        )
        console.print(f"[blue]Namespaces:[/blue] {namespaces}")
        if webhook_url:
            console.print(f"[blue]Webhook alerts:[/blue] {webhook_url}")
        if slack_webhook_url:
            console.print("[blue]Slack alerts:[/blue] enabled")

    console.print(
        f"\n[bold]kube-foresight dashboard[/bold] running at "
        f"[link=http://{host}:{port}]http://{host}:{port}[/link]\n"
    )

    uvicorn.run(
        app,
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )
