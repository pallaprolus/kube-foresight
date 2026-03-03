"""Rich terminal output formatters."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from kube_foresight.models import CostEstimate, DeploymentProfile, Recommendation
from kube_foresight.recommender.patch import format_cpu, format_memory


def render_analysis_table(profiles: list[DeploymentProfile], console: Console) -> None:
    """Render a rich table of deployment profiles with usage stats."""
    table = Table(title="Over-Provisioned Deployments", show_lines=True)
    table.add_column("#", justify="right", style="bold", width=3)
    table.add_column("Deployment", style="cyan")
    table.add_column("Replicas", justify="right")
    table.add_column("CPU Req", justify="right")
    table.add_column("CPU p95", justify="right")
    table.add_column("CPU Util%", justify="right")
    table.add_column("Mem Req", justify="right")
    table.add_column("Mem p95", justify="right")
    table.add_column("Mem Util%", justify="right")
    table.add_column("Waste", justify="right", style="red bold")

    for i, p in enumerate(profiles, 1):
        cpu_util_pct = f"{p.cpu_utilization_ratio * 100:.0f}%"
        mem_util_pct = f"{p.memory_utilization_ratio * 100:.0f}%"
        waste_score = f"{p.over_provisioning_score:.2f}"

        table.add_row(
            str(i),
            p.name,
            str(p.replica_count),
            format_cpu(p.cpu_spec.request),
            format_cpu(p.cpu_stats.p95),
            _colorize_util(cpu_util_pct, p.cpu_utilization_ratio),
            format_memory(p.memory_spec.request),
            format_memory(p.memory_stats.p95),
            _colorize_util(mem_util_pct, p.memory_utilization_ratio),
            waste_score,
        )

    console.print()
    console.print(table)


def render_recommendations_table(
    recommendations: list[Recommendation], console: Console
) -> None:
    """Render recommendations with current vs recommended and confidence."""
    table = Table(title="Right-Sizing Recommendations", show_lines=True)
    table.add_column("#", justify="right", style="bold", width=3)
    table.add_column("Deployment", style="cyan")
    table.add_column("CPU Req", justify="right")
    table.add_column("CPU Rec", justify="right", style="green")
    table.add_column("CPU \u0394", justify="right")
    table.add_column("Mem Req", justify="right")
    table.add_column("Mem Rec", justify="right", style="green")
    table.add_column("Mem \u0394", justify="right")
    table.add_column("Confidence", justify="center")

    for i, r in enumerate(recommendations, 1):
        cpu_delta = f"-{r.cpu_reduction_pct:.0f}%"
        mem_delta = f"-{r.memory_reduction_pct:.0f}%"
        conf_style = {"high": "green", "medium": "yellow", "low": "red"}.get(
            r.confidence.value, "white"
        )

        table.add_row(
            str(i),
            r.deployment_name,
            format_cpu(r.current_cpu_request),
            format_cpu(r.recommended_cpu_request),
            f"[red]{cpu_delta}[/red]" if r.cpu_reduction_pct > 0 else cpu_delta,
            format_memory(r.current_memory_request),
            format_memory(r.recommended_memory_request),
            f"[red]{mem_delta}[/red]" if r.memory_reduction_pct > 0 else mem_delta,
            f"[{conf_style}]{r.confidence.value}[/{conf_style}]",
        )

    console.print()
    console.print(table)


def render_cost_summary(
    estimates: list[CostEstimate],
    total_monthly: float,
    total_annual: float,
    console: Console,
) -> None:
    """Render cost savings with a summary panel."""
    table = Table(title="Cost Impact (AWS us-east-1, on-demand)", show_lines=True)
    table.add_column("Deployment", style="cyan")
    table.add_column("Replicas", justify="right")
    table.add_column("Current $/mo", justify="right")
    table.add_column("Optimized $/mo", justify="right", style="green")
    table.add_column("Savings $/mo", justify="right", style="bold red")

    for e in estimates:
        table.add_row(
            e.deployment_name,
            str(e.replica_count),
            f"${e.current_monthly_cost_usd:,.2f}",
            f"${e.recommended_monthly_cost_usd:,.2f}",
            f"${e.monthly_savings_usd:,.2f}",
        )

    console.print()
    console.print(table)
    console.print()
    console.print(
        Panel(
            f"[bold green]Monthly savings: ${total_monthly:,.2f}[/bold green]\n"
            f"[bold green]Annual savings:  ${total_annual:,.2f}[/bold green]",
            title="Total Estimated Savings",
            border_style="green",
        )
    )


def render_patch_summary(patch_files: list[str], console: Console) -> None:
    """Render list of generated patch files."""
    console.print()
    console.print(f"[bold green]Generated {len(patch_files)} patch file(s):[/bold green]")
    for f in patch_files:
        console.print(f"  {f}")
    console.print()
    console.print("[dim]Apply with: kubectl apply -f <patch-file>[/dim]")


def _colorize_util(text: str, ratio: float) -> str:
    if ratio < 0.3:
        return f"[red]{text}[/red]"
    if ratio < 0.6:
        return f"[yellow]{text}[/yellow]"
    return f"[green]{text}[/green]"
