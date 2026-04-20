"""HTML page routes."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from kube_foresight.dashboard.serializers import (
    serialize_cost,
    serialize_forecast,
    serialize_multi_cloud_summary,
    serialize_profile,
    serialize_recommendation,
    serialize_report,
)

router = APIRouter()
logger = logging.getLogger("kube_foresight.dashboard.routes")


def _redirect(path: str) -> RedirectResponse:
    """Redirect to a path."""
    return RedirectResponse(url=path)


def _ctx(request: Request, **kwargs) -> dict:
    """Build template context with common variables."""
    service = request.app.state.analysis_service
    ctx = {
        "has_results": service.has_results,
        "status": service.status.value,
    }
    ctx.update(kwargs)
    return ctx


# --- Main pages (3 pages + detail) ---


@router.get("/", response_class=HTMLResponse)
@router.get("/overview", response_class=HTMLResponse)
async def page_overview(request: Request):
    service = request.app.state.analysis_service
    # Auto-analyze on first load using defaults from env vars
    if not service.has_results:
        mode = getattr(request.app.state, "default_mode", "mock")
        namespace = getattr(request.app.state, "default_namespace", "default")
        try:
            service.run_analysis(mode=mode, namespace=namespace, seed=42)
        except Exception:
            logger.warning("Auto-analysis failed on first load", exc_info=True)

    report = service.get_report()
    if report:
        data = serialize_report(report)
        at_risk = [serialize_forecast(fc) for fc in service.get_at_risk_deployments()]
    else:
        data = None
        at_risk = []

    # Discover available namespaces for the settings dropdown
    mode = getattr(request.app.state, "default_mode", "mock")
    default_ns = getattr(request.app.state, "default_namespace", "default")
    namespaces = service.get_available_namespaces(mode=mode)

    return request.app.state.templates.TemplateResponse(
        request,
        "pages/overview.html",
        _ctx(
            request,
            active_page="overview",
            report=data,
            report_json=json.dumps(data) if data else "null",
            at_risk=at_risk,
            default_mode=mode,
            default_namespace=default_ns,
            namespaces=namespaces,
        ),
    )


@router.get("/recommendations", response_class=HTMLResponse)
async def page_recommendations(request: Request):
    service = request.app.state.analysis_service
    if not service.has_results:
        return _redirect("/")
    report = service.get_report()
    data = serialize_report(report)
    sort_by = request.query_params.get("sort", "cpu_reduction_pct")
    reverse = sort_by not in ("deployment_name", "confidence")
    data["recommendations"].sort(key=lambda r: r.get(sort_by, 0), reverse=reverse)
    # Build patch map for inline patches
    patches = service.get_all_patches()
    patch_map = {p["name"]: p["yaml"] for p in patches}
    return request.app.state.templates.TemplateResponse(
        request,
        "pages/recommendations.html",
        _ctx(
            request,
            active_page="recommendations",
            report=data,
            report_json=json.dumps(data),
            patch_map=patch_map,
        ),
    )


@router.get("/costs", response_class=HTMLResponse)
async def page_costs(request: Request):
    service = request.app.state.analysis_service
    if not service.has_results:
        return _redirect("/")
    report = service.get_report()
    data = serialize_report(report)
    # Multi-cloud cost comparison (moved from executive)
    multi_costs = service.get_multi_cloud_costs()
    cloud_summary = serialize_multi_cloud_summary(multi_costs)
    # Top 5 savings opportunities
    sorted_costs = sorted(data["costs"], key=lambda c: c["monthly_savings_usd"], reverse=True)
    top_savings = sorted_costs[:5]
    return request.app.state.templates.TemplateResponse(
        request,
        "pages/costs.html",
        _ctx(
            request,
            active_page="costs",
            report=data,
            report_json=json.dumps(data),
            provider_name=service.provider_name,
            cloud_summary=cloud_summary,
            cloud_summary_json=json.dumps(cloud_summary),
            top_savings=top_savings,
        ),
    )


@router.get("/deployments/{name}", response_class=HTMLResponse)
async def page_deployment_detail(request: Request, name: str):
    service = request.app.state.analysis_service
    if not service.has_results:
        return _redirect("/")
    detail = service.get_deployment_detail(name)
    if not detail:
        return _redirect("/")
    profile = serialize_profile(detail.profile)
    rec = serialize_recommendation(detail.recommendation) if detail.recommendation else None
    cost = serialize_cost(detail.cost_estimate) if detail.cost_estimate else None
    ts_data = service.get_timeseries_data(name)
    fc = service.get_forecast(name)
    fc_data = serialize_forecast(fc) if fc else None
    hpa_conflicts = [
        {"conflict_type": c.conflict_type, "hpa_name": c.hpa_name, "message": c.message}
        for c in detail.hpa_conflicts
    ]
    return request.app.state.templates.TemplateResponse(
        request,
        "pages/deployment.html",
        _ctx(
            request,
            active_page="overview",
            profile=profile,
            recommendation=rec,
            cost=cost,
            patch_yaml=detail.patch_yaml,
            timeseries_json=json.dumps(ts_data),
            forecast=fc_data,
            forecast_json=json.dumps(fc_data),
            hpa_conflicts=hpa_conflicts,
        ),
    )


# --- Backward-compatibility redirects ---


@router.get("/executive", response_class=HTMLResponse)
async def redirect_executive():
    return _redirect("/")


@router.get("/patches", response_class=HTMLResponse)
async def redirect_patches():
    return _redirect("/recommendations")
