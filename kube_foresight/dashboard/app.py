"""FastAPI application setup."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from kube_foresight.dashboard.service import AnalysisService
from kube_foresight.logging_config import configure_logging
from kube_foresight.scheduler import BackgroundScheduler, SchedulerConfig

_BASE_DIR = Path(__file__).parent
logger = logging.getLogger("kube_foresight.dashboard")


def _safe_int(env_var: str, default: int) -> int:
    """Parse an integer env var, falling back to default on error."""
    raw = os.environ.get(env_var, "")
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning(
            "Invalid integer for %s=%r, using default %d",
            env_var, raw, default,
        )
        return default


def _safe_float(env_var: str, default: float) -> float:
    """Parse a float env var, falling back to default on error."""
    raw = os.environ.get(env_var, "")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning(
            "Invalid float for %s=%r, using default %s",
            env_var, raw, default,
        )
        return default


_VALID_MODES = frozenset({"mock", "k8s", "prometheus"})
_VALID_STRATEGIES = frozenset({"p95", "p99", "max"})


def _build_scheduler_config() -> SchedulerConfig:
    """Build scheduler config from environment variables."""
    namespaces_str = os.environ.get("KF_NAMESPACES", "")
    namespaces = (
        [n.strip() for n in namespaces_str.split(",") if n.strip()]
        if namespaces_str
        else []
    )

    mode = os.environ.get("KF_MODE", "k8s")
    if mode not in _VALID_MODES:
        logger.warning(
            "Invalid KF_MODE=%r, using 'k8s'. Valid: %s",
            mode, ", ".join(sorted(_VALID_MODES)),
        )
        mode = "k8s"

    strategy = os.environ.get("KF_STRATEGY", "p99")
    if strategy not in _VALID_STRATEGIES:
        logger.warning(
            "Invalid KF_STRATEGY=%r, using 'p99'. Valid: %s",
            strategy, ", ".join(sorted(_VALID_STRATEGIES)),
        )
        strategy = "p99"

    headroom = _safe_float("KF_HEADROOM", 0.20)
    if not 0.0 <= headroom <= 1.0:
        logger.warning(
            "KF_HEADROOM=%s out of range [0, 1], clamping",
            headroom,
        )
        headroom = max(0.0, min(1.0, headroom))

    return SchedulerConfig(
        enabled=os.environ.get(
            "KF_SCHEDULER_ENABLED", "",
        ).lower() in ("1", "true", "yes"),
        collect_interval_seconds=_safe_int(
            "KF_COLLECT_INTERVAL", 300,
        ),
        analysis_interval_seconds=_safe_int(
            "KF_ANALYSIS_INTERVAL", 900,
        ),
        mode=mode,
        prometheus_url=os.environ.get("KF_PROMETHEUS_URL") or None,
        namespaces=namespaces or ["default"],
        db_path=os.environ.get("KF_DB_PATH") or None,
        lookback_hours=_safe_int("KF_LOOKBACK_HOURS", 168),
        strategy=strategy,
        headroom=headroom,
        top_n=_safe_int("KF_TOP_N", 10),
        webhook_url=os.environ.get("KF_WEBHOOK_URL") or None,
        slack_webhook_url=os.environ.get(
            "KF_SLACK_WEBHOOK_URL",
        ) or None,
    )


def build_app() -> FastAPI:
    log_format = os.environ.get("KF_LOG_FORMAT", "text")
    configure_logging(fmt=log_format)

    scheduler_config = _build_scheduler_config()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup: start scheduler if enabled
        if scheduler_config.enabled:
            scheduler = BackgroundScheduler(scheduler_config, app.state.analysis_service)
            app.state.scheduler = scheduler
            await scheduler.start()
            logger.info("Background scheduler started")
        else:
            app.state.scheduler = None
        yield
        # Shutdown: stop scheduler
        if app.state.scheduler:
            await app.state.scheduler.stop()

    app = FastAPI(
        title="kube-foresight Dashboard",
        description="Kubernetes Resource Optimization Dashboard",
        lifespan=lifespan,
    )

    # Initialize eagerly so CLI --demo can access before uvicorn starts
    app.state.analysis_service = AnalysisService()
    app.state.templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))

    # Expose configured defaults so the dashboard form can pre-fill them
    app.state.default_db_path = (
        os.environ.get("KF_DB_PATH", "")
        or str(Path.home() / ".kube-foresight" / "metrics.db")
    )
    app.state.default_mode = os.environ.get("KF_MODE", "mock")
    app.state.default_namespace = os.environ.get("KF_NAMESPACES", "default")
    app.mount("/static", StaticFiles(directory=str(_BASE_DIR / "static")), name="static")

    # Health / readiness probes
    @app.get("/healthz")
    async def healthz():
        return JSONResponse({"status": "ok"})

    @app.get("/readyz")
    async def readyz():
        service = app.state.analysis_service
        scheduler = getattr(app.state, "scheduler", None)
        return JSONResponse({
            "status": "ok",
            "analysis_status": service.status.value,
            "has_results": service.has_results,
            "scheduler_running": scheduler.is_running if scheduler else False,
        })

    # Scheduler status endpoint
    @app.get("/api/scheduler/status")
    async def scheduler_status():
        scheduler = getattr(app.state, "scheduler", None)
        if not scheduler:
            return JSONResponse({"enabled": False})
        return JSONResponse({"enabled": True, **scheduler.status})

    # Audit log endpoints
    @app.get("/api/audit")
    async def api_audit_log():
        service = app.state.analysis_service
        entries = service.audit_log.get_recent(limit=50)
        return [
            {
                "id": e.id,
                "timestamp": e.timestamp.isoformat(),
                "action": e.action,
                "deployment_name": e.deployment_name,
                "namespace": e.namespace,
                "dry_run": e.dry_run,
                "success": e.success,
                "message": e.message,
            }
            for e in entries
        ]

    from kube_foresight.dashboard.routes.api import router as api_router
    from kube_foresight.dashboard.routes.pages import router as page_router

    app.include_router(api_router)
    app.include_router(page_router)

    logger.info("kube-foresight dashboard initialized")
    return app
