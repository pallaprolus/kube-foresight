"""Rich terminal output formatters."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from kube_foresight.models import (
    CostEstimate,
    DeploymentForecast,
    DeploymentProfile,
    Recommendation,
    SizingCategory,
)
from kube_foresight.recommender.patch import format_cpu, format_memory

_CATEGORY_STYLES = {
    SizingCategory.UNDER_PROVISIONED: ("[red]UNDER-SIZED[/red]", 0),
    SizingCategory.OVER_PROVISIONED: ("[yellow]OVER-SIZED[/yellow]", 1),
    SizingCategory.RIGHT_SIZED: ("[green]RIGHT-SIZED[/green]", 2),
}


def render_analysis_table(profiles: list[DeploymentProfile], console: Console) -> None:
    """Render a rich table of deployment profiles with usage stats."""
    # Sort: under-provisioned first (urgent), then over-provisioned, then right-sized
    sorted_profiles = sorted(
        profiles, key=lambda p: _CATEGORY_STYLES[p.sizing_category][1]
    )

    table = Table(title="Deployment Resource Analysis", show_lines=True)
    table.add_column("#", justify="right", style="bold", width=3)
    table.add_column("Deployment", style="cyan")
    table.add_column("Status", justify="center")
    table.add_column("Replicas", justify="right")
    table.add_column("CPU Req", justify="right")
    table.add_column("CPU p95", justify="right")
    table.add_column("CPU Util%", justify="right")
    table.add_column("Mem Req", justify="right")
    table.add_column("Mem p95", justify="right")
    table.add_column("Mem Util%", justify="right")

    for i, p in enumerate(sorted_profiles, 1):
        cpu_util_pct = f"{p.cpu_utilization_ratio * 100:.0f}%"
        mem_util_pct = f"{p.memory_utilization_ratio * 100:.0f}%"
        status_label = _CATEGORY_STYLES[p.sizing_category][0]

        table.add_row(
            str(i),
            p.name,
            status_label,
            str(p.replica_count),
            format_cpu(p.cpu_spec.request),
            format_cpu(p.cpu_stats.p95),
            _colorize_util(cpu_util_pct, p.cpu_utilization_ratio),
            format_memory(p.memory_spec.request),
            format_memory(p.memory_stats.p95),
            _colorize_util(mem_util_pct, p.memory_utilization_ratio),
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
        cpu_delta = _format_delta(r.cpu_reduction_pct)
        mem_delta = _format_delta(r.memory_reduction_pct)
        conf_style = {"high": "green", "medium": "yellow", "low": "red"}.get(
            r.confidence.value, "white"
        )

        table.add_row(
            str(i),
            r.deployment_name,
            format_cpu(r.current_cpu_request),
            format_cpu(r.recommended_cpu_request),
            cpu_delta,
            format_memory(r.current_memory_request),
            format_memory(r.recommended_memory_request),
            mem_delta,
            f"[{conf_style}]{r.confidence.value}[/{conf_style}]",
        )

    console.print()
    console.print(table)


def render_cost_summary(
    estimates: list[CostEstimate],
    total_monthly: float,
    total_annual: float,
    console: Console,
    provider_name: str = "AWS (us-east-1, on-demand)",
) -> None:
    """Render cost savings with a summary panel."""
    table = Table(title=f"Cost Impact ({provider_name})", show_lines=True)
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


def render_forecast_table(forecasts: list[DeploymentForecast], console: Console) -> None:
    """Render forecast results as a Rich table."""
    risk_order = {"critical": 0, "warning": 1, "ok": 2}
    sorted_fc = sorted(forecasts, key=lambda f: risk_order.get(f.risk_level, 3))

    table = Table(title="Resource Usage Forecasts", show_lines=True)
    table.add_column("#", justify="right", style="bold", width=3)
    table.add_column("Deployment", style="cyan")
    table.add_column("Risk", justify="center")
    table.add_column("CPU Trend", justify="center")
    table.add_column("Mem Trend", justify="center")
    table.add_column("CPU Breach", justify="right")
    table.add_column("Mem Breach", justify="right")
    table.add_column("CPU R\u00b2", justify="right")
    table.add_column("Mem R\u00b2", justify="right")

    for i, fc in enumerate(sorted_fc, 1):
        risk_style = {"critical": "red", "warning": "yellow", "ok": "green"}[fc.risk_level]
        cpu_breach = _format_breach_days(fc.cpu_forecast.days_until_request_breach)
        mem_breach = _format_breach_days(fc.memory_forecast.days_until_request_breach)

        table.add_row(
            str(i),
            fc.deployment_name,
            f"[{risk_style}]{fc.risk_level.upper()}[/{risk_style}]",
            fc.cpu_forecast.trend.value,
            fc.memory_forecast.trend.value,
            cpu_breach,
            mem_breach,
            f"{fc.cpu_forecast.r_squared:.2f}",
            f"{fc.memory_forecast.r_squared:.2f}",
        )

    console.print()
    console.print(table)

    # Summary panel with at-risk count
    at_risk = [f for f in forecasts if f.risk_level != "ok"]
    if at_risk:
        lines = []
        for fc in sorted(at_risk, key=lambda f: risk_order.get(f.risk_level, 3)):
            risk_style = {"critical": "red", "warning": "yellow"}[fc.risk_level]
            lines.append(f"[{risk_style}]{fc.risk_level.upper()}[/{risk_style}] {fc.summary}")
        console.print()
        console.print(
            Panel("\n".join(lines), title=f"At Risk ({len(at_risk)})", border_style="red")
        )
    else:
        console.print()
        console.print(
            "[bold green]All deployments are stable"
            " — no breaches predicted.[/bold green]"
        )


def _format_breach_days(days: float | None) -> str:
    """Format breach timeline with color."""
    if days is None:
        return "[green]--[/green]"
    if days <= 0:
        return "[red]BREACHED[/red]"
    if days <= 7:
        return f"[red]{days:.0f}d[/red]"
    if days <= 14:
        return f"[yellow]{days:.0f}d[/yellow]"
    return f"{days:.0f}d"


def _colorize_util(text: str, ratio: float) -> str:
    if ratio < 0.3:
        return f"[red]{text}[/red]"
    if ratio < 0.6:
        return f"[yellow]{text}[/yellow]"
    return f"[green]{text}[/green]"


def _format_delta(reduction_pct: float) -> str:
    """Format a reduction percentage with color.

    Positive = decrease (over-provisioned, shown in red).
    Negative = increase (under-provisioned, shown in green).
    """
    if reduction_pct > 0:
        return f"[red]-{reduction_pct:.0f}%[/red]"
    if reduction_pct < 0:
        return f"[green]+{abs(reduction_pct):.0f}%[/green]"
    return "0%"
