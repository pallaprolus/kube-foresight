"""Trend detection, linear regression, and resource usage forecasting."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

import numpy as np

from kube_foresight.models import (
    ContainerMetrics,
    DeploymentForecast,
    ForecastPoint,
    ResourceForecast,
    ResourceType,
    TrendDirection,
)

MIN_HOURLY_POINTS = 24  # minimum hours of data for a meaningful forecast


def _resample_to_hourly(
    time_series: list[tuple[datetime, float]],
) -> tuple[np.ndarray, np.ndarray]:
    """Downsample time-series to hourly means.

    Returns (hours_since_start, hourly_mean_values).
    """
    if not time_series:
        return np.array([]), np.array([])

    t0 = time_series[0][0]
    buckets: dict[int, list[float]] = defaultdict(list)
    for ts, val in time_series:
        hour_idx = int((ts - t0).total_seconds() / 3600)
        buckets[hour_idx].append(val)

    hours = sorted(buckets.keys())
    x = np.array(hours, dtype=float)
    y = np.array([float(np.mean(buckets[h])) for h in hours])
    return x, y


def _linear_regression(
    x: np.ndarray, y: np.ndarray
) -> tuple[float, float, float]:
    """Fit y = slope*x + intercept. Returns (slope, intercept, r_squared)."""
    if len(x) < 2:
        return 0.0, float(np.mean(y)) if len(y) > 0 else 0.0, 0.0

    coefficients = np.polyfit(x, y, deg=1)
    slope, intercept = float(coefficients[0]), float(coefficients[1])

    y_pred = np.polyval(coefficients, x)
    ss_res = float(np.sum((y - y_pred) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
    r_squared = max(0.0, r_squared)

    return slope, intercept, r_squared


def _autocorrelation_at_lag(values: np.ndarray, lag: int) -> float:
    """Compute autocorrelation at a specific lag."""
    n = len(values)
    if lag >= n or lag < 1:
        return 0.0
    mean = float(np.mean(values))
    var = float(np.var(values))
    if var < 1e-12:
        return 0.0
    original = values[: n - lag]
    shifted = values[lag:]
    return float(np.mean((original - mean) * (shifted - mean)) / var)


def _detect_trend(
    x_hours: np.ndarray,
    y_values: np.ndarray,
    slope: float,
    r_squared: float,
) -> TrendDirection:
    """Classify the time-series trend."""
    # Check for cyclicity (need at least 2 days)
    if len(y_values) >= 48:
        detrended = y_values - (slope * x_hours + float(np.mean(y_values)))
        autocorr_24h = _autocorrelation_at_lag(detrended, lag=24)
        if autocorr_24h > 0.4:
            return TrendDirection.CYCLIC

    # Relative slope: daily change as fraction of the mean
    mean_val = float(np.mean(y_values))
    if mean_val > 0:
        relative_slope_per_day = abs(slope * 24) / mean_val
    else:
        relative_slope_per_day = 0.0

    if relative_slope_per_day > 0.01 and r_squared > 0.3:
        return TrendDirection.GROWING if slope > 0 else TrendDirection.DECLINING

    return TrendDirection.STEADY


def _compute_breach_days(
    slope: float,
    intercept: float,
    current_x_hours: float,
    threshold: float,
) -> float | None:
    """Compute days until the regression line reaches the threshold.

    Returns None if the line is flat/declining or threshold is already below
    the current predicted value.
    """
    if slope <= 0:
        return None

    breach_x = (threshold - intercept) / slope
    hours_from_now = breach_x - current_x_hours

    if hours_from_now <= 0:
        return 0.0  # already breached

    return round(hours_from_now / 24.0, 1)


def _generate_forecast_points(
    slope: float,
    intercept: float,
    std_residual: float,
    last_timestamp: datetime,
    last_x_hours: float,
    forecast_days: int = 30,
    step_hours: int = 6,
) -> list[ForecastPoint]:
    """Generate projected data points with 95% confidence bands."""
    points: list[ForecastPoint] = []
    n_steps = (forecast_days * 24) // step_hours
    band = 1.96 * std_residual  # 95% CI

    for i in range(1, n_steps + 1):
        future_hours = last_x_hours + i * step_hours
        future_ts = last_timestamp + timedelta(hours=i * step_hours)
        predicted = slope * future_hours + intercept

        points.append(
            ForecastPoint(
                timestamp=future_ts,
                value=max(0.0, predicted),
                lower_bound=max(0.0, predicted - band),
                upper_bound=max(0.0, predicted + band),
            )
        )

    return points


def _classify_risk(
    cpu_fc: ResourceForecast, mem_fc: ResourceForecast
) -> str:
    """Classify overall deployment risk based on breach timelines."""
    for fc in (cpu_fc, mem_fc):
        if fc.days_until_limit_breach is not None and fc.days_until_limit_breach <= 7:
            return "critical"
        if fc.days_until_request_breach is not None and fc.days_until_request_breach <= 3:
            return "critical"

    for fc in (cpu_fc, mem_fc):
        if fc.days_until_request_breach is not None and fc.days_until_request_breach <= 14:
            return "warning"

    return "ok"


def _build_summary(
    name: str,
    cpu_fc: ResourceForecast,
    mem_fc: ResourceForecast,
    risk: str,
) -> str:
    """Build a human-readable one-line summary."""
    parts: list[str] = []

    for label, fc in [("CPU", cpu_fc), ("Memory", mem_fc)]:
        if fc.trend == TrendDirection.GROWING:
            if fc.days_until_request_breach is not None:
                days = fc.days_until_request_breach
                if days <= 0:
                    parts.append(f"{label} has breached request")
                else:
                    parts.append(f"{label} will breach request in {days:.0f}d")
            else:
                parts.append(f"{label} is growing")

    if not parts:
        return f"{name}: resource usage is stable"

    return f"{name}: " + "; ".join(parts)


def forecast_resource(
    time_series: list[tuple[datetime, float]],
    resource_type: ResourceType,
    request_value: float,
    limit_value: float,
    forecast_days: int = 30,
) -> ResourceForecast:
    """Generate a forecast for a single resource type."""
    x_hours, y_values = _resample_to_hourly(time_series)

    if len(x_hours) < MIN_HOURLY_POINTS:
        last_val = float(y_values[-1]) if len(y_values) > 0 else 0.0
        return ResourceForecast(
            resource_type=resource_type,
            trend=TrendDirection.STEADY,
            slope_per_day=0.0,
            r_squared=0.0,
            current_value=last_val,
            request_value=request_value,
            limit_value=limit_value,
            days_until_request_breach=None,
            days_until_limit_breach=None,
            forecast_points=[],
            sufficient_data=False,
        )

    slope, intercept, r_squared = _linear_regression(x_hours, y_values)
    trend = _detect_trend(x_hours, y_values, slope, r_squared)

    current_x = float(x_hours[-1])
    current_value = float(y_values[-1])

    # Residual std for confidence bands
    y_pred = slope * x_hours + intercept
    residuals = y_values - y_pred
    std_residual = float(np.std(residuals)) if len(residuals) > 2 else 0.0

    # Breach predictions
    days_to_request = _compute_breach_days(slope, intercept, current_x, request_value)
    days_to_limit = _compute_breach_days(slope, intercept, current_x, limit_value)

    # Generate forecast points
    last_ts = time_series[-1][0]
    forecast_points = _generate_forecast_points(
        slope, intercept, std_residual, last_ts, current_x, forecast_days
    )

    return ResourceForecast(
        resource_type=resource_type,
        trend=trend,
        slope_per_day=round(slope * 24, 6),
        r_squared=round(r_squared, 4),
        current_value=round(current_value, 6),
        request_value=request_value,
        limit_value=limit_value,
        days_until_request_breach=days_to_request,
        days_until_limit_breach=days_to_limit,
        forecast_points=forecast_points,
        sufficient_data=True,
    )


def generate_forecast(
    metrics: ContainerMetrics,
    forecast_days: int = 30,
) -> DeploymentForecast:
    """Generate a complete deployment forecast from container metrics."""
    cpu_fc = forecast_resource(
        metrics.cpu_usage,
        ResourceType.CPU,
        metrics.cpu_spec.request,
        metrics.cpu_spec.limit,
        forecast_days,
    )
    mem_fc = forecast_resource(
        metrics.memory_usage,
        ResourceType.MEMORY,
        metrics.memory_spec.request,
        metrics.memory_spec.limit,
        forecast_days,
    )

    risk_level = _classify_risk(cpu_fc, mem_fc)
    summary = _build_summary(metrics.deployment_name, cpu_fc, mem_fc, risk_level)

    return DeploymentForecast(
        deployment_name=metrics.deployment_name,
        namespace=metrics.namespace,
        cpu_forecast=cpu_fc,
        memory_forecast=mem_fc,
        risk_level=risk_level,
        summary=summary,
    )
