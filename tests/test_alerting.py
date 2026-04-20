"""Tests for the alerting module."""

from unittest.mock import MagicMock, patch

import pytest

from kube_foresight.alerting import (
    _alerted,
    _build_alert_payload,
    _build_slack_blocks,
    _should_alert,
    send_alerts,
)
from kube_foresight.models import (
    DeploymentForecast,
    ResourceForecast,
    TrendDirection,
)


def _make_forecast(
    name: str = "test-deploy",
    namespace: str = "default",
    risk_level: str = "warning",
    cpu_trend: TrendDirection = TrendDirection.GROWING,
    mem_trend: TrendDirection = TrendDirection.STEADY,
    cpu_breach: float | None = 10.0,
    mem_breach: float | None = None,
) -> DeploymentForecast:
    cpu_fc = ResourceForecast(
        resource_type="cpu",
        trend=cpu_trend,
        slope_per_day=0.01,
        r_squared=0.8,
        current_value=0.3,
        request_value=0.5,
        limit_value=1.0,
        days_until_request_breach=cpu_breach,
        days_until_limit_breach=None,
        forecast_points=[],
        sufficient_data=True,
    )
    mem_fc = ResourceForecast(
        resource_type="memory",
        trend=mem_trend,
        slope_per_day=0.0,
        r_squared=0.5,
        current_value=256e6,
        request_value=512e6,
        limit_value=1024e6,
        days_until_request_breach=mem_breach,
        days_until_limit_breach=None,
        forecast_points=[],
        sufficient_data=True,
    )
    return DeploymentForecast(
        deployment_name=name,
        namespace=namespace,
        cpu_forecast=cpu_fc,
        memory_forecast=mem_fc,
        risk_level=risk_level,
        summary=f"{name} is {risk_level}",
    )


@pytest.fixture(autouse=True)
def reset_alert_state():
    """Reset the dedup state before each test."""
    _alerted.clear()
    yield
    _alerted.clear()


class TestBuildAlertPayload:
    def test_basic_payload(self):
        fc = _make_forecast(risk_level="critical")
        payload = _build_alert_payload([fc])
        assert payload["source"] == "kube-foresight"
        assert payload["severity"] == "critical"
        assert payload["total_at_risk"] == 1
        assert payload["critical_count"] == 1
        assert payload["warning_count"] == 0
        assert len(payload["deployments"]) == 1
        assert payload["deployments"][0]["name"] == "test-deploy"

    def test_mixed_severity(self):
        forecasts = [
            _make_forecast(name="a", risk_level="critical"),
            _make_forecast(name="b", risk_level="warning"),
        ]
        payload = _build_alert_payload(forecasts)
        assert payload["severity"] == "critical"
        assert payload["critical_count"] == 1
        assert payload["warning_count"] == 1

    def test_warning_only(self):
        payload = _build_alert_payload([_make_forecast(risk_level="warning")])
        assert payload["severity"] == "warning"


class TestBuildSlackBlocks:
    def test_basic_blocks(self):
        fc = _make_forecast()
        blocks = _build_slack_blocks([fc])
        assert "blocks" in blocks
        assert len(blocks["blocks"]) >= 3  # header, summary, divider, deploy

    def test_critical_uses_rotating_light(self):
        fc = _make_forecast(risk_level="critical")
        blocks = _build_slack_blocks([fc])
        header = blocks["blocks"][0]["text"]["text"]
        assert "rotating_light" in header

    def test_caps_at_10_deployments(self):
        forecasts = [_make_forecast(name=f"deploy-{i}") for i in range(15)]
        blocks = _build_slack_blocks(forecasts)
        # header + summary + divider + 10 deploys + overflow context = 14
        deploy_blocks = [b for b in blocks["blocks"] if b["type"] == "section"]
        assert len(deploy_blocks) <= 12  # summary + 10 deploys max


class TestShouldAlert:
    def test_first_alert_passes(self):
        fc = _make_forecast()
        result = _should_alert([fc])
        assert len(result) == 1

    def test_same_risk_deduped(self):
        fc = _make_forecast()
        _should_alert([fc])  # first time
        result = _should_alert([fc])  # same risk
        assert len(result) == 0

    def test_escalated_risk_passes(self):
        fc_warning = _make_forecast(risk_level="warning")
        _should_alert([fc_warning])
        fc_critical = _make_forecast(risk_level="critical")
        result = _should_alert([fc_critical])
        assert len(result) == 1

    def test_resolved_cleans_up(self):
        fc = _make_forecast(name="temp-deploy")
        _should_alert([fc])
        assert "temp-deploy" in _alerted
        # Next cycle, deploy not in list → cleaned up
        _should_alert([])
        assert "temp-deploy" not in _alerted


class TestSendAlerts:
    @pytest.mark.asyncio
    async def test_no_forecasts_no_call(self):
        with patch("kube_foresight.alerting.requests") as mock_req:
            await send_alerts([], webhook_url="http://x", slack_webhook_url="http://y")
            mock_req.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_urls_no_call(self):
        fc = _make_forecast()
        with patch("kube_foresight.alerting.requests") as mock_req:
            await send_alerts([fc])
            mock_req.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_webhook_called(self):
        fc = _make_forecast()
        with patch("kube_foresight.alerting.requests") as mock_req:
            mock_req.post.return_value = MagicMock(status_code=200)
            mock_req.post.return_value.raise_for_status = MagicMock()
            await send_alerts([fc], webhook_url="http://hooks.example.com/alert")
            mock_req.post.assert_called_once()
            call_args = mock_req.post.call_args
            assert call_args[0][0] == "http://hooks.example.com/alert"
            assert "json" in call_args[1]

    @pytest.mark.asyncio
    async def test_slack_called(self):
        fc = _make_forecast()
        with patch("kube_foresight.alerting.requests") as mock_req:
            mock_req.post.return_value = MagicMock(status_code=200)
            mock_req.post.return_value.raise_for_status = MagicMock()
            await send_alerts([fc], slack_webhook_url="https://hooks.slack.com/test")
            mock_req.post.assert_called_once()
            call_args = mock_req.post.call_args
            assert "blocks" in call_args[1]["json"]

    @pytest.mark.asyncio
    async def test_webhook_error_handled(self):
        fc = _make_forecast()
        with patch("kube_foresight.alerting.requests") as mock_req:
            mock_req.post.side_effect = Exception("Connection refused")
            # Should not raise
            await send_alerts([fc], webhook_url="http://bad-url")

    @pytest.mark.asyncio
    async def test_dedup_prevents_second_call(self):
        fc = _make_forecast()
        with patch("kube_foresight.alerting.requests") as mock_req:
            mock_req.post.return_value = MagicMock(status_code=200)
            mock_req.post.return_value.raise_for_status = MagicMock()
            await send_alerts([fc], webhook_url="http://hooks.example.com")
            await send_alerts([fc], webhook_url="http://hooks.example.com")
            # Only called once due to dedup
            assert mock_req.post.call_count == 1
