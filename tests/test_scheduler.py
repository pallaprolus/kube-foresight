"""Tests for the background scheduler."""

from unittest.mock import MagicMock

import pytest

from kube_foresight.scheduler import BackgroundScheduler, SchedulerConfig


@pytest.fixture
def config():
    return SchedulerConfig(
        enabled=True,
        collect_interval_seconds=1,
        analysis_interval_seconds=2,
        mode="mock",
        namespaces=["default"],
    )


@pytest.fixture
def mock_service():
    service = MagicMock()
    service.has_results = False
    service.get_at_risk_deployments.return_value = []
    service.run_analysis = MagicMock()
    return service


class TestSchedulerConfig:
    def test_defaults(self):
        cfg = SchedulerConfig()
        assert cfg.enabled is False
        assert cfg.collect_interval_seconds == 300
        assert cfg.analysis_interval_seconds == 900
        assert cfg.mode == "k8s"
        assert cfg.namespaces == ["default"]
        assert cfg.webhook_url is None
        assert cfg.slack_webhook_url is None

    def test_custom_values(self):
        cfg = SchedulerConfig(
            enabled=True,
            collect_interval_seconds=60,
            analysis_interval_seconds=120,
            mode="prometheus",
            namespaces=["ns1", "ns2"],
            webhook_url="http://example.com",
            slack_webhook_url="https://hooks.slack.com/x",
        )
        assert cfg.enabled is True
        assert cfg.namespaces == ["ns1", "ns2"]
        assert cfg.webhook_url == "http://example.com"


class TestBackgroundScheduler:
    def test_initial_state(self, config, mock_service):
        scheduler = BackgroundScheduler(config, mock_service)
        assert scheduler.is_running is False
        assert scheduler.status["running"] is False

    @pytest.mark.asyncio
    async def test_start_and_stop(self, config, mock_service):
        scheduler = BackgroundScheduler(config, mock_service)
        await scheduler.start()
        assert scheduler.is_running is True
        assert scheduler.status["running"] is True
        await scheduler.stop()
        assert scheduler.is_running is False

    @pytest.mark.asyncio
    async def test_double_start_is_noop(self, config, mock_service):
        scheduler = BackgroundScheduler(config, mock_service)
        await scheduler.start()
        await scheduler.start()  # should not error
        assert scheduler.is_running is True
        await scheduler.stop()

    def test_status_includes_config(self, config, mock_service):
        scheduler = BackgroundScheduler(config, mock_service)
        status = scheduler.status
        assert status["collect_interval_seconds"] == 1
        assert status["analysis_interval_seconds"] == 2
        assert status["namespaces"] == ["default"]
        assert status["collect_count"] == 0
        assert status["analysis_count"] == 0
        assert status["last_collect"] is None
        assert status["last_analysis"] is None
