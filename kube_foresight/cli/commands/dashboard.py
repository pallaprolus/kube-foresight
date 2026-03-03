"""Dashboard command: launch the kube-foresight web UI."""

from __future__ import annotations

import typer
from rich.console import Console

console = Console()


def dashboard(
    port: int = typer.Option(8080, "--port", "-p", help="Port to listen on"),
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind to"),
    demo: bool = typer.Option(False, "--demo", "-d", help="Pre-load demo analysis results"),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload for development"),
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
            strategy="p95",
            headroom=0.20,
            top_n=10,
            seed=42,
        )
        console.print("[green]Demo data loaded.[/green]")

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
