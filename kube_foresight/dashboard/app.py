"""FastAPI application setup."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from kube_foresight.dashboard.service import AnalysisService

_BASE_DIR = Path(__file__).parent


def build_app() -> FastAPI:
    app = FastAPI(
        title="kube-foresight Dashboard",
        description="Kubernetes Resource Optimization Dashboard",
    )

    # Initialize eagerly so CLI --demo can access before uvicorn starts
    app.state.analysis_service = AnalysisService()
    app.state.templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))
    app.mount("/static", StaticFiles(directory=str(_BASE_DIR / "static")), name="static")

    from kube_foresight.dashboard.routes.api import router as api_router
    from kube_foresight.dashboard.routes.pages import router as page_router

    app.include_router(api_router)
    app.include_router(page_router)

    return app
