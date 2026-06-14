"""Background scheduler for continuous metric collection and analysis."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger("kube_foresight.scheduler")


@dataclass
class SchedulerConfig:
    """Configuration for the background scheduler."""

    enabled: bool = False
    collect_interval_seconds: int = 300  # 5 minutes
    analysis_interval_seconds: int = 900  # 15 minutes
    mode: str = "k8s"
    prometheus_url: str | None = None
    namespaces: list[str] = field(default_factory=lambda: ["default"])
    db_path: str | None = None
    lookback_hours: int = 168
    strategy: str = "p99"
    headroom: float = 0.20
    top_n: int = 10
    # Alerting
    webhook_url: str | None = None
    slack_webhook_url: str | None = None


class BackgroundScheduler:
    """Runs metric collection and analysis on a timer in the background.

    Designed to be started as an asyncio task alongside the FastAPI server.
    """

    def __init__(self, config: SchedulerConfig, analysis_service) -> None:
        self._config = config
        self._service = analysis_service
        self._running = False
        self._collect_task: asyncio.Task | None = None
        self._analyze_task: asyncio.Task | None = None
        self._last_collect: datetime | None = None
        self._last_analysis: datetime | None = None
        self._collect_count = 0
        self._analysis_count = 0

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def status(self) -> dict:
        return {
            "running": self._running,
            "collect_interval_seconds": self._config.collect_interval_seconds,
            "analysis_interval_seconds": self._config.analysis_interval_seconds,
            "namespaces": self._config.namespaces,
            "last_collect": self._last_collect.isoformat() if self._last_collect else None,
            "last_analysis": self._last_analysis.isoformat() if self._last_analysis else None,
            "collect_count": self._collect_count,
            "analysis_count": self._analysis_count,
        }

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        logger.info(
            "Scheduler started: collect every %ds, analyze every %ds, namespaces=%s",
            self._config.collect_interval_seconds,
            self._config.analysis_interval_seconds,
            self._config.namespaces,
        )
        self._collect_task = asyncio.create_task(self._collect_loop())
        self._analyze_task = asyncio.create_task(self._analyze_loop())

    async def stop(self) -> None:
        self._running = False
        for task in (self._collect_task, self._analyze_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        logger.info("Scheduler stopped")

    async def _collect_loop(self) -> None:
        """Periodically take metric snapshots."""
        from kube_foresight.collector import get_collector

        while self._running:
            try:
                collector = get_collector(
                    mode=self._config.mode,
                    prometheus_url=self._config.prometheus_url,
                    db_path=self._config.db_path,
                )
                for ns in self._config.namespaces:
                    if hasattr(collector, "take_snapshot"):
                        count = collector.take_snapshot(ns)
                        logger.info("Collected %d metrics for namespace '%s'", count, ns)
                    else:
                        logger.debug(
                            "Collector %s does not support snapshots",
                            type(collector).__name__,
                        )
                self._last_collect = datetime.now(timezone.utc)
                self._collect_count += 1
            except Exception:
                logger.exception("Collection failed")

            await asyncio.sleep(self._config.collect_interval_seconds)

    async def _analyze_loop(self) -> None:
        """Periodically run analysis and send alerts."""
        # Wait for first collection to complete
        await asyncio.sleep(min(30, self._config.collect_interval_seconds + 5))

        while self._running:
            try:
                for ns in self._config.namespaces:
                    self._service.run_analysis(
                        mode=self._config.mode,
                        prometheus_url=self._config.prometheus_url,
                        namespace=ns,
                        lookback_hours=self._config.lookback_hours,
                        strategy=self._config.strategy,
                        headroom=self._config.headroom,
                        top_n=self._config.top_n,
                        db_path=self._config.db_path,
                    )
                    logger.info("Analysis completed for namespace '%s'", ns)

                self._last_analysis = datetime.now(timezone.utc)
                self._analysis_count += 1

                # Send alerts if configured
                await self._send_alerts()

            except Exception:
                logger.exception("Analysis failed")

            await asyncio.sleep(self._config.analysis_interval_seconds)

    async def _send_alerts(self) -> None:
        """Send webhook/Slack alerts for at-risk deployments."""
        at_risk = self._service.get_at_risk_deployments()
        if not at_risk:
            return

        from kube_foresight.alerting import send_alerts

        await send_alerts(
            at_risk,
            webhook_url=self._config.webhook_url,
            slack_webhook_url=self._config.slack_webhook_url,
        )
