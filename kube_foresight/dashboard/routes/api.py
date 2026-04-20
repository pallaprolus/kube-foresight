"""API and HTMX partial routes."""

from __future__ import annotations

import html as html_mod
import io
import zipfile

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from kube_foresight.collector.store import MetricsStore
from kube_foresight.dashboard.serializers import serialize_forecast, serialize_report

router = APIRouter()

_VALID_MODES = {"mock", "prometheus", "k8s"}
_VALID_STRATEGIES = {"p95", "p99", "max"}


def _sanitize_error(err: Exception) -> str:
    """Return a safe, HTML-escaped error message without leaking internals."""
    msg = str(err)
    # Strip file paths
    if "/" in msg or "\\" in msg:
        msg = msg.split("\n")[0]
    return html_mod.escape(msg[:200])


def _validate_params(
    mode: str, strategy: str, lookback_hours: int, top_n: int, headroom: float,
) -> str | None:
    """Return an error message if any parameter is invalid, else None."""
    if mode not in _VALID_MODES:
        return f"Invalid mode '{html_mod.escape(mode)}'. Valid: {', '.join(sorted(_VALID_MODES))}"
    if strategy not in _VALID_STRATEGIES:
        return (
            f"Invalid strategy '{html_mod.escape(strategy)}'. "
            f"Valid: {', '.join(sorted(_VALID_STRATEGIES))}"
        )
    if not 1 <= lookback_hours <= 8760:
        return "lookback_hours must be between 1 and 8760"
    if not 1 <= top_n <= 100:
        return "top_n must be between 1 and 100"
    if not 0.0 <= headroom <= 1.0:
        return "headroom must be between 0.0 and 1.0"
    return None


def _k8s_kwargs(mode: str, db_path: str | None) -> dict:
    """Build extra kwargs when mode is 'k8s'."""
    if mode != "k8s":
        return {}
    kwargs: dict = {}
    if db_path and db_path.strip():
        kwargs["db_path"] = db_path.strip()
    return kwargs


@router.post("/api/connect")
async def api_connect(
    request: Request,
    mode: str = Form("mock"),
    prometheus_url: str = Form(""),
    db_path: str = Form(""),
):
    if mode not in _VALID_MODES:
        return JSONResponse(
            {"connected": False, "message": f"Invalid mode '{mode}'"},
            status_code=400,
        )
    service = request.app.state.analysis_service
    url = prometheus_url.strip() if prometheus_url else None
    ok, msg = service.test_connection(
        mode=mode, prometheus_url=url, **_k8s_kwargs(mode, db_path),
    )
    return {"connected": ok, "message": msg}


@router.post("/api/analyze")
async def api_analyze(
    request: Request,
    mode: str = Form("mock"),
    prometheus_url: str = Form(""),
    db_path: str = Form(""),
    namespace: str = Form("demo-app"),
    lookback_hours: int = Form(168),
    strategy: str = Form("p95"),
    headroom: float = Form(0.20),
    top_n: int = Form(10),
    seed: int = Form(42),
):
    err = _validate_params(mode, strategy, lookback_hours, top_n, headroom)
    if err:
        return JSONResponse({"error": err}, status_code=400)
    service = request.app.state.analysis_service
    url = prometheus_url.strip() if prometheus_url else None
    report = service.run_analysis(
        mode=mode,
        prometheus_url=url,
        namespace=namespace,
        lookback_hours=lookback_hours,
        strategy=strategy,
        headroom=headroom,
        top_n=top_n,
        seed=seed,
        **_k8s_kwargs(mode, db_path),
    )
    return serialize_report(report)


@router.get("/api/deployments/{name}/forecast")
async def api_deployment_forecast(request: Request, name: str):
    service = request.app.state.analysis_service
    if not service.has_results:
        return JSONResponse({"error": "No analysis results"}, status_code=400)
    fc = service.get_forecast(name)
    if not fc:
        return JSONResponse({"error": "Deployment not found"}, status_code=404)
    return serialize_forecast(fc)


@router.get("/api/deployments/{name}/timeseries")
async def api_deployment_timeseries(request: Request, name: str):
    service = request.app.state.analysis_service
    return service.get_timeseries_data(name)


@router.post("/api/patches/{name}/dry-run")
async def api_patch_dry_run(request: Request, name: str):
    service = request.app.state.analysis_service
    if not service.has_results:
        return JSONResponse({"error": "No analysis results"}, status_code=400)
    source_ip = request.client.host if request.client else ""
    ok, msg = service.apply_patch(name, dry_run=True, source_ip=source_ip)
    status = 200 if ok else 400
    return JSONResponse({"success": ok, "message": msg}, status_code=status)


@router.post("/api/patches/{name}/apply")
async def api_patch_apply(request: Request, name: str):
    service = request.app.state.analysis_service
    if not service.has_results:
        return JSONResponse({"error": "No analysis results"}, status_code=400)
    source_ip = request.client.host if request.client else ""
    ok, msg = service.apply_patch(name, dry_run=False, source_ip=source_ip)
    status = 200 if ok else 400
    return JSONResponse({"success": ok, "message": msg}, status_code=status)


@router.get("/api/patches/download")
async def api_patches_download(request: Request):
    service = request.app.state.analysis_service
    patches = service.get_all_patches()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in patches:
            zf.writestr(f"{p['name']}-patch.yaml", p["yaml"])
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=kube-foresight-patches.zip"},
    )


# --- HTMX partials ---


@router.post("/partials/namespaces", response_class=HTMLResponse)
async def partial_namespaces(
    request: Request,
    db_path: str = Form(""),
):
    """Discover namespaces in a k8s SQLite DB and return as HTML options."""
    path = db_path.strip() if db_path else None
    if not path:
        return HTMLResponse(
            '<span class="text-amber-600 text-sm">Enter a DB path first</span>'
        )
    try:
        store = MetricsStore(db_path=path)
        namespaces = store.get_namespaces()
    except Exception as e:
        safe = html_mod.escape(str(e)[:200])
        return HTMLResponse(
            f'<span class="text-red-500 text-sm">&#10007; {safe}</span>'
        )
    if not namespaces:
        return HTMLResponse(
            '<span class="text-amber-600 text-sm">No data found in this database</span>'
        )
    # Build clickable namespace buttons
    parts = ['<div class="flex flex-wrap gap-2 mt-1">']
    for ns in namespaces:
        name = html_mod.escape(ns["namespace"])
        deploys = ns["deployments"]
        samples = ns["snapshots"]
        # JS: set namespace input, reset all buttons, highlight clicked
        onclick = (
            f"document.getElementById('namespace').value='{name}';"
            "this.parentElement.querySelectorAll('button').forEach("
            "b => b.className = b.className"
            ".replace('bg-kf-accent text-white',"
            "'bg-gray-100 text-gray-700'));"
            "this.className = this.className"
            ".replace('bg-gray-100 text-gray-700',"
            "'bg-kf-accent text-white')"
        )
        cls = (
            "px-3 py-1.5 rounded-lg text-xs font-medium "
            "bg-gray-100 text-gray-700 hover:bg-gray-200 "
            "transition-colors border border-gray-200"
        )
        label = (
            f'{name} <span class="text-gray-400">'
            f"({deploys} deploys, {samples} samples)</span>"
        )
        parts.append(
            f'<button type="button" onclick="{onclick}"'
            f' class="{cls}">{label}</button>'
        )
    parts.append('</div>')
    return HTMLResponse("".join(parts))


@router.post("/partials/connect", response_class=HTMLResponse)
async def partial_connect(
    request: Request,
    mode: str = Form("mock"),
    prometheus_url: str = Form(""),
    db_path: str = Form(""),
):
    if mode not in _VALID_MODES:
        return HTMLResponse(
            '<span class="text-red-400 text-sm">&#10007; Invalid mode</span>'
        )
    service = request.app.state.analysis_service
    url = prometheus_url.strip() if prometheus_url else None
    ok, msg = service.test_connection(
        mode=mode, prometheus_url=url, **_k8s_kwargs(mode, db_path),
    )
    safe_msg = html_mod.escape(msg)
    if ok:
        resp = f'<span class="text-green-400 text-sm">&#10003; {safe_msg}</span>'
    else:
        resp = f'<span class="text-red-400 text-sm">&#10007; {safe_msg}</span>'
    return HTMLResponse(resp)


@router.post("/partials/analyze", response_class=HTMLResponse)
async def partial_analyze(
    request: Request,
    mode: str = Form("mock"),
    prometheus_url: str = Form(""),
    db_path: str = Form(""),
    namespace: str = Form("demo-app"),
    lookback_hours: int = Form(168),
    strategy: str = Form("p95"),
    headroom: float = Form(0.20),
    top_n: int = Form(10),
    seed: int = Form(42),
):
    err = _validate_params(mode, strategy, lookback_hours, top_n, headroom)
    if err:
        return HTMLResponse(f'<div class="text-red-600 font-medium">Error: {err}</div>')
    service = request.app.state.analysis_service
    url = prometheus_url.strip() if prometheus_url else None
    try:
        service.run_analysis(
            mode=mode,
            prometheus_url=url,
            namespace=namespace,
            lookback_hours=lookback_hours,
            strategy=strategy,
            headroom=headroom,
            top_n=top_n,
            seed=seed,
            **_k8s_kwargs(mode, db_path),
        )
        response = HTMLResponse(
            '<div class="text-green-600 font-medium">Analysis complete! Redirecting...</div>'
        )
        response.headers["HX-Redirect"] = "/"
        return response
    except Exception as e:
        safe_msg = _sanitize_error(e)
        return HTMLResponse(
            f'<div class="text-red-600 font-medium">Error: {safe_msg}</div>'
        )


@router.post("/partials/patches/{name}/dry-run", response_class=HTMLResponse)
async def partial_patch_dry_run(request: Request, name: str):
    service = request.app.state.analysis_service
    if not service.has_results:
        return HTMLResponse('<span class="text-red-500 text-sm">No analysis results</span>')
    source_ip = request.client.host if request.client else ""
    ok, msg = service.apply_patch(name, dry_run=True, source_ip=source_ip)
    safe_msg = html_mod.escape(msg)
    if ok:
        return HTMLResponse(
            f'<span class="text-green-600 text-sm">&#10003; Dry-run OK: {safe_msg}</span>'
        )
    return HTMLResponse(
        f'<span class="text-red-500 text-sm">&#10007; {safe_msg}</span>'
    )


@router.post("/partials/patches/{name}/apply", response_class=HTMLResponse)
async def partial_patch_apply(request: Request, name: str):
    service = request.app.state.analysis_service
    if not service.has_results:
        return HTMLResponse('<span class="text-red-500 text-sm">No analysis results</span>')
    source_ip = request.client.host if request.client else ""
    ok, msg = service.apply_patch(name, dry_run=False, source_ip=source_ip)
    safe_msg = html_mod.escape(msg)
    if ok:
        return HTMLResponse(
            f'<span class="text-green-600 text-sm font-medium">&#10003; Applied: {safe_msg}</span>'
        )
    return HTMLResponse(
        f'<span class="text-red-500 text-sm">&#10007; Failed: {safe_msg}</span>'
    )


@router.post("/partials/executive/refresh", response_class=HTMLResponse)
async def partial_executive_refresh(request: Request):
    """Re-run analysis with the same params used previously, then redirect to /executive."""
    service = request.app.state.analysis_service
    params = service.last_analysis_params
    if not params:
        return HTMLResponse(
            '<div class="text-red-600 font-medium">No previous analysis to refresh.</div>'
        )
    try:
        if "namespaces" in params:
            service.run_multi_namespace_analysis(**params)
        else:
            service.run_analysis(**params)
        response = HTMLResponse(
            '<div class="text-green-600 font-medium">Refresh complete! Redirecting...</div>'
        )
        response.headers["HX-Redirect"] = "/"
        return response
    except Exception as e:
        safe_msg = _sanitize_error(e)
        return HTMLResponse(
            f'<div class="text-red-600 font-medium">Error: {safe_msg}</div>'
        )
