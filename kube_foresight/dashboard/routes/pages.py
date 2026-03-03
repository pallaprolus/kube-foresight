"""HTML page routes."""

from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from kube_foresight.dashboard.serializers import serialize_cost, serialize_profile, serialize_recommendation, serialize_report

router = APIRouter()


def _ctx(request: Request, **kwargs) -> dict:
    """Build template context with common variables."""
    service = request.app.state.analysis_service
    ctx = {
        "has_results": service.has_results,
        "status": service.status.value,
    }
    ctx.update(kwargs)
    return ctx


@router.get("/", response_class=HTMLResponse)
async def page_home(request: Request):
    return request.app.state.templates.TemplateResponse(
        request, "pages/home.html", _ctx(request, active_page="home")
    )


@router.get("/overview", response_class=HTMLResponse)
async def page_overview(request: Request):
    service = request.app.state.analysis_service
    if not service.has_results:
        return RedirectResponse(url="/")
    report = service.get_report()
    data = serialize_report(report)
    return request.app.state.templates.TemplateResponse(
        request,
        "pages/overview.html",
        _ctx(request, active_page="overview", report=data, report_json=json.dumps(data)),
    )


@router.get("/deployments/{name}", response_class=HTMLResponse)
async def page_deployment_detail(request: Request, name: str):
    service = request.app.state.analysis_service
    if not service.has_results:
        return RedirectResponse(url="/")
    detail = service.get_deployment_detail(name)
    if not detail:
        return RedirectResponse(url="/overview")
    profile = serialize_profile(detail.profile)
    rec = serialize_recommendation(detail.recommendation) if detail.recommendation else None
    cost = serialize_cost(detail.cost_estimate) if detail.cost_estimate else None
    ts_data = service.get_timeseries_data(name)
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
        ),
    )


@router.get("/recommendations", response_class=HTMLResponse)
async def page_recommendations(request: Request):
    service = request.app.state.analysis_service
    if not service.has_results:
        return RedirectResponse(url="/")
    report = service.get_report()
    data = serialize_report(report)
    sort_by = request.query_params.get("sort", "cpu_reduction_pct")
    reverse = sort_by not in ("deployment_name", "confidence")
    data["recommendations"].sort(key=lambda r: r.get(sort_by, 0), reverse=reverse)
    return request.app.state.templates.TemplateResponse(
        request,
        "pages/recommendations.html",
        _ctx(request, active_page="recommendations", report=data, report_json=json.dumps(data)),
    )


@router.get("/costs", response_class=HTMLResponse)
async def page_costs(request: Request):
    service = request.app.state.analysis_service
    if not service.has_results:
        return RedirectResponse(url="/")
    report = service.get_report()
    data = serialize_report(report)
    return request.app.state.templates.TemplateResponse(
        request,
        "pages/costs.html",
        _ctx(request, active_page="costs", report=data, report_json=json.dumps(data)),
    )


@router.get("/patches", response_class=HTMLResponse)
async def page_patches(request: Request):
    service = request.app.state.analysis_service
    if not service.has_results:
        return RedirectResponse(url="/")
    patches = service.get_all_patches()
    return request.app.state.templates.TemplateResponse(
        request,
        "pages/patches.html",
        _ctx(request, active_page="patches", patches=patches),
    )
