"""CLI command: collect — poll Kubernetes Metrics API and store snapshots."""

from __future__ import annotations

import logging
import signal
import time
from pathlib import Path

import typer
from rich.console import Console

console = Console()
logger = logging.getLogger("kube_foresight.collect")


def collect(
    namespace: str = typer.Option("default", help="Kubernetes namespace to collect from."),
    interval: int = typer.Option(300, help="Polling interval in seconds (0 = --once)."),
    once: bool = typer.Option(False, help="Take a single snapshot and exit."),
    retention: int = typer.Option(720, help="Data retention in hours (default 30 days)."),
    downsample_after: int = typer.Option(
        168,
        help="Keep full resolution for this many hours (default 7 days).",
    ),
    db_path: str = typer.Option(
        None,
        help="SQLite database path (default: ~/.kube-foresight/metrics.db).",
    ),
    kubeconfig: str = typer.Option(None, help="Path to kubeconfig file."),
    context: str = typer.Option(None, help="Kubernetes context name."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
) -> None:
    """Poll the Kubernetes Metrics API and store snapshots in SQLite.

    Run as a background daemon or CronJob to accumulate historical data.
    Use --once for single-shot execution (ideal for K8s CronJobs).
    """
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    )

    from kube_foresight.collector.k8s import K8sMetricsCollector

    path = Path(db_path) if db_path else None
    collector = K8sMetricsCollector(db_path=path, kubeconfig=kubeconfig, context=context)

    # Verify connection
    console.print("[bold]kube-foresight collect[/bold]")
    console.print(f"  Namespace:  {namespace}")
    console.print(f"  DB path:    {collector.store.db_path}")
    console.print(f"  Interval:   {'once' if once else f'{interval}s'}")
    console.print(f"  Retention:  {retention}h ({retention // 24}d)")
    console.print()

    ok, msg = collector.check_connection()
    if not ok:
        console.print(f"[red]Connection failed:[/red] {msg}")
        raise typer.Exit(code=1)
    console.print(f"[green]Connected:[/green] {msg}")

    # Graceful shutdown
    _shutdown = False

    def _handle_signal(signum, frame):  # noqa: ARG001
        nonlocal _shutdown
        _shutdown = True
        console.print("\n[yellow]Shutting down gracefully...[/yellow]")

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # Main loop
    iteration = 0
    while not _shutdown:
        iteration += 1
        try:
            count = collector.take_snapshot(namespace)
            console.print(
                f"[dim][{time.strftime('%H:%M:%S')}][/dim] "
                f"Snapshot #{iteration}: {count} container metrics"
            )
        except Exception as e:
            logger.error("Snapshot failed: %s", e)
            console.print(f"[red]Snapshot #{iteration} failed:[/red] {e}")

        # Periodic maintenance
        if iteration % 12 == 0:  # Every ~1 hour at 5-min intervals
            try:
                purged = collector.store.purge_old_data(retention_hours=retention)
                if purged:
                    logger.info("Purged %d old rows", purged)
                downsampled = collector.store.downsample_old_data(full_res_hours=downsample_after)
                if downsampled:
                    logger.info("Downsampled %d old rows", downsampled)
            except Exception as e:
                logger.warning("Maintenance failed: %s", e)

        if once:
            break

        # Sleep with interrupt check
        for _ in range(interval):
            if _shutdown:
                break
            time.sleep(1)

    console.print("[bold green]Done.[/bold green]")
