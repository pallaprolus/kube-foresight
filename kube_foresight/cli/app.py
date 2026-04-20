"""CLI entry point for kube-foresight."""

from __future__ import annotations

import typer

from kube_foresight.cli.commands.analyze import analyze
from kube_foresight.cli.commands.collect import collect
from kube_foresight.cli.commands.dashboard import dashboard
from kube_foresight.cli.commands.demo import demo
from kube_foresight.cli.commands.forecast import forecast
from kube_foresight.cli.commands.patch import patch
from kube_foresight.cli.commands.recommend import recommend

app = typer.Typer(
    name="kube-foresight",
    help="Predictive Resource Optimizer for Kubernetes. "
    "Identifies over-provisioned deployments and generates right-sizing patches.",
    add_completion=False,
)

app.command()(analyze)
app.command()(collect)
app.command()(dashboard)
app.command()(forecast)
app.command()(recommend)
app.command()(patch)
app.command()(demo)


def main() -> None:
    app()
