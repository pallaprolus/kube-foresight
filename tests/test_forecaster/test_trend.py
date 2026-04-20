"""Tests for the forecaster trend detection and forecast generation."""

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from kube_foresight.forecaster.trend import (
    _autocorrelation_at_lag,
    _compute_breach_days,
    _linear_regression,
    _resample_to_hourly,
    forecast_resource,
    generate_forecast,
)
from kube_foresight.models import (
    ResourceType,
    TrendDirection,
)

# ── Helpers ─────────────────────────────────────────────────────


def _make_timeseries(values, hours=168, step_minutes=5):
    """Build a list[tuple[datetime, float]] from a numpy array."""
    n = len(values)
    now = datetime.now(timezone.utc)
    t0 = now - timedelta(hours=hours)
    step = timedelta(minutes=step_minutes)
    return [(t0 + i * step, float(values[i])) for i in range(n)]


def _growing_series(n=2016, base=0.1):
    """Simulate the mock 'growing' pattern: linear increase over time."""
    t = np.arange(n)
    return base * (1 + 0.5 * t / n)


def _steady_series(n=2016, base=0.04):
    """Flat baseline with small noise."""
    rng = np.random.default_rng(42)
    return np.full(n, base) + rng.normal(0, base * 0.05, n)


def _diurnal_series(n=2016, base=0.08):
    """24-hour sine wave pattern."""
    t = np.arange(n)
    points_per_day = 288  # 5-min intervals
    daily_phase = (t % points_per_day) / points_per_day
    return base * (1 + 0.4 * np.sin(2 * np.pi * daily_phase - np.pi / 2))


# ── _linear_regression tests ───────────────────────────────────


def test_linear_regression_perfect_line():
    x = np.arange(100, dtype=float)
    y = 2.0 * x + 5.0
    slope, intercept, r_sq = _linear_regression(x, y)
    assert slope == pytest.approx(2.0, abs=1e-6)
    assert intercept == pytest.approx(5.0, abs=1e-6)
    assert r_sq == pytest.approx(1.0, abs=1e-6)


def test_linear_regression_flat():
    x = np.arange(100, dtype=float)
    y = np.full(100, 3.0)
    slope, intercept, r_sq = _linear_regression(x, y)
    assert abs(slope) < 1e-6


def test_linear_regression_noisy():
    rng = np.random.default_rng(42)
    x = np.arange(200, dtype=float)
    y = 0.5 * x + 10.0 + rng.normal(0, 5, 200)
    slope, intercept, r_sq = _linear_regression(x, y)
    assert slope == pytest.approx(0.5, abs=0.1)
    assert r_sq > 0.5


def test_linear_regression_single_point():
    x = np.array([0.0])
    y = np.array([5.0])
    slope, intercept, r_sq = _linear_regression(x, y)
    assert slope == 0.0
    assert intercept == 5.0


# ── _autocorrelation_at_lag tests ──────────────────────────────


def test_autocorrelation_periodic_signal():
    t = np.arange(168, dtype=float)
    signal = np.sin(2 * np.pi * t / 24)
    ac = _autocorrelation_at_lag(signal, lag=24)
    assert ac > 0.8


def test_autocorrelation_white_noise():
    rng = np.random.default_rng(42)
    noise = rng.normal(0, 1, 200)
    ac = _autocorrelation_at_lag(noise, lag=24)
    assert abs(ac) < 0.3


# ── Trend detection via forecast_resource ──────────────────────


def test_detect_growing_trend():
    values = _growing_series()
    ts = _make_timeseries(values)
    fc = forecast_resource(ts, ResourceType.CPU, request_value=1.0, limit_value=2.0)
    assert fc.trend == TrendDirection.GROWING
    assert fc.slope_per_day > 0
    assert fc.r_squared > 0.5
    assert fc.sufficient_data is True


def test_detect_steady_trend():
    values = _steady_series()
    ts = _make_timeseries(values)
    fc = forecast_resource(ts, ResourceType.CPU, request_value=0.5, limit_value=1.0)
    assert fc.trend == TrendDirection.STEADY


def test_detect_cyclic_trend():
    values = _diurnal_series()
    ts = _make_timeseries(values)
    fc = forecast_resource(ts, ResourceType.CPU, request_value=1.0, limit_value=2.0)
    assert fc.trend == TrendDirection.CYCLIC


# ── Breach prediction tests ───────────────────────────────────


def test_growing_predicts_breach():
    values = _growing_series(base=0.1)
    ts = _make_timeseries(values)
    # Low request so growth can reach it
    fc = forecast_resource(ts, ResourceType.CPU, request_value=0.2, limit_value=0.4)
    assert fc.days_until_request_breach is not None
    assert fc.days_until_request_breach > 0


def test_steady_no_breach():
    values = _steady_series(base=0.04)
    ts = _make_timeseries(values)
    fc = forecast_resource(ts, ResourceType.CPU, request_value=0.5, limit_value=1.0)
    assert fc.days_until_request_breach is None


def test_breach_days_already_breached():
    days = _compute_breach_days(slope=0.01, intercept=10.0, current_x_hours=100.0, threshold=5.0)
    assert days == 0.0


def test_breach_days_declining_no_breach():
    days = _compute_breach_days(slope=-0.01, intercept=5.0, current_x_hours=100.0, threshold=10.0)
    assert days is None


# ── Insufficient data test ─────────────────────────────────────


def test_insufficient_data():
    ts = [(datetime.now(timezone.utc) + timedelta(minutes=i), 0.5) for i in range(5)]
    fc = forecast_resource(ts, ResourceType.CPU, request_value=1.0, limit_value=2.0)
    assert fc.sufficient_data is False
    assert fc.trend == TrendDirection.STEADY
    assert fc.forecast_points == []


# ── Forecast points tests ──────────────────────────────────────


def test_forecast_points_in_future():
    values = _growing_series()
    ts = _make_timeseries(values)
    fc = forecast_resource(ts, ResourceType.CPU, request_value=1.0, limit_value=2.0)
    assert len(fc.forecast_points) > 0
    last_historical = ts[-1][0]
    for fp in fc.forecast_points:
        assert fp.timestamp > last_historical
        assert fp.value >= 0.0
        assert fp.upper_bound >= fp.value


def test_forecast_points_have_confidence_bands():
    values = _growing_series()
    ts = _make_timeseries(values)
    fc = forecast_resource(ts, ResourceType.CPU, request_value=1.0, limit_value=2.0)
    for fp in fc.forecast_points:
        assert fp.upper_bound >= fp.lower_bound


# ── Integration: generate_forecast ─────────────────────────────


def test_generate_forecast_with_mock_data(mock_metrics):
    """Test forecasting on the mock log-aggregator (growing pattern)."""
    log_agg = [m for m in mock_metrics if m.deployment_name == "log-aggregator"][0]
    fc = generate_forecast(log_agg, forecast_days=30)
    assert fc.deployment_name == "log-aggregator"
    assert fc.cpu_forecast.trend == TrendDirection.GROWING
    assert fc.risk_level in ("critical", "warning", "ok")
    assert len(fc.summary) > 0


def test_generate_forecast_steady_deployment(mock_metrics):
    """Test forecasting on a steady deployment."""
    notif = [m for m in mock_metrics if m.deployment_name == "notification-svc"][0]
    fc = generate_forecast(notif, forecast_days=30)
    assert fc.deployment_name == "notification-svc"
    assert fc.risk_level == "ok"


def test_generate_forecast_covers_both_resources(mock_metrics):
    """Both CPU and memory forecasts should be populated."""
    m = mock_metrics[0]
    fc = generate_forecast(m, forecast_days=14)
    assert fc.cpu_forecast.resource_type == ResourceType.CPU
    assert fc.memory_forecast.resource_type == ResourceType.MEMORY
    assert fc.cpu_forecast.sufficient_data is True
    assert fc.memory_forecast.sufficient_data is True


# ── Resample tests ─────────────────────────────────────────────


def test_resample_to_hourly():
    """5-minute data for 2 hours should produce 2 hourly buckets."""
    now = datetime.now(timezone.utc)
    ts = [(now + timedelta(minutes=5 * i), float(i)) for i in range(24)]
    x, y = _resample_to_hourly(ts)
    assert len(x) == 2  # 0-59min → hour 0, 60-115min → hour 1
    assert y[0] == pytest.approx(np.mean(range(12)), abs=0.1)
