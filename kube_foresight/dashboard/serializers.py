"""Convert domain dataclasses to JSON-safe dicts for API responses and templates."""

from __future__ import annotations

from kube_foresight.models import (
    AnalysisReport,
    CostEstimate,
    DeploymentForecast,
    DeploymentProfile,
    Recommendation,
    ResourceForecast,
)
from kube_foresight.pricing.providers import get_provider
from kube_foresight.recommender.patch import format_cpu, format_memory


def serialize_profile(p: DeploymentProfile) -> dict:
    return {
        "name": p.name,
        "namespace": p.namespace,
        "replica_count": p.replica_count,
        "cpu_request": p.cpu_spec.request,
        "cpu_request_fmt": format_cpu(p.cpu_spec.request),
        "cpu_limit": p.cpu_spec.limit,
        "memory_request": p.memory_spec.request,
        "memory_request_fmt": format_memory(p.memory_spec.request),
        "memory_limit": p.memory_spec.limit,
        "cpu_utilization_pct": round(p.cpu_utilization_ratio * 100, 1),
        "memory_utilization_pct": round(p.memory_utilization_ratio * 100, 1),
        "over_provisioning_score": round(p.over_provisioning_score, 3),
        "waste_pct": round(p.over_provisioning_score * 100, 0),
        "sizing_category": p.sizing_category.value,
        "cpu_p95_fmt": format_cpu(p.cpu_stats.p95),
        "mem_p95_fmt": format_memory(p.memory_stats.p95),
        "cpu_stats": {
            "mean": round(p.cpu_stats.mean, 4),
            "median": round(p.cpu_stats.median, 4),
            "p95": round(p.cpu_stats.p95, 4),
            "p99": round(p.cpu_stats.p99, 4),
            "max": round(p.cpu_stats.max, 4),
            "min": round(p.cpu_stats.min, 4),
            "std_dev": round(p.cpu_stats.std_dev, 4),
            "sample_count": p.cpu_stats.sample_count,
        },
        "memory_stats": {
            "mean": round(p.memory_stats.mean / (1024**2), 1),
            "median": round(p.memory_stats.median / (1024**2), 1),
            "p95": round(p.memory_stats.p95 / (1024**2), 1),
            "p99": round(p.memory_stats.p99 / (1024**2), 1),
            "max": round(p.memory_stats.max / (1024**2), 1),
            "min": round(p.memory_stats.min / (1024**2), 1),
            "std_dev": round(p.memory_stats.std_dev / (1024**2), 1),
            "sample_count": p.memory_stats.sample_count,
        },
    }


def serialize_recommendation(r: Recommendation) -> dict:
    return {
        "deployment_name": r.deployment_name,
        "namespace": r.namespace,
        "strategy": r.strategy,
        "headroom": r.headroom,
        "current_cpu_request": r.current_cpu_request,
        "current_cpu_request_fmt": format_cpu(r.current_cpu_request),
        "recommended_cpu_request": r.recommended_cpu_request,
        "recommended_cpu_request_fmt": format_cpu(r.recommended_cpu_request),
        "current_memory_request": r.current_memory_request,
        "current_memory_request_fmt": format_memory(r.current_memory_request),
        "recommended_memory_request": r.recommended_memory_request,
        "recommended_memory_request_fmt": format_memory(r.recommended_memory_request),
        "cpu_reduction_pct": r.cpu_reduction_pct,
        "memory_reduction_pct": r.memory_reduction_pct,
        "confidence": r.confidence.value,
    }


def serialize_cost(c: CostEstimate) -> dict:
    return {
        "deployment_name": c.deployment_name,
        "namespace": c.namespace,
        "replica_count": c.replica_count,
        "current_monthly_cost_usd": c.current_monthly_cost_usd,
        "recommended_monthly_cost_usd": c.recommended_monthly_cost_usd,
        "monthly_savings_usd": c.monthly_savings_usd,
        "annual_savings_usd": c.annual_savings_usd,
    }


def serialize_resource_forecast(rf: ResourceForecast) -> dict:
    return {
        "resource_type": rf.resource_type.value,
        "trend": rf.trend.value,
        "slope_per_day": rf.slope_per_day,
        "r_squared": rf.r_squared,
        "current_value": rf.current_value,
        "request_value": rf.request_value,
        "limit_value": rf.limit_value,
        "days_until_request_breach": rf.days_until_request_breach,
        "days_until_limit_breach": rf.days_until_limit_breach,
        "sufficient_data": rf.sufficient_data,
        "forecast_points": [
            {
                "timestamp": fp.timestamp.isoformat(),
                "value": round(fp.value, 6),
                "lower_bound": round(fp.lower_bound, 6),
                "upper_bound": round(fp.upper_bound, 6),
            }
            for fp in rf.forecast_points
        ],
    }


def serialize_forecast(fc: DeploymentForecast) -> dict:
    return {
        "deployment_name": fc.deployment_name,
        "namespace": fc.namespace,
        "cpu_forecast": serialize_resource_forecast(fc.cpu_forecast),
        "memory_forecast": serialize_resource_forecast(fc.memory_forecast),
        "risk_level": fc.risk_level,
        "summary": fc.summary,
    }


def serialize_report(report: AnalysisReport) -> dict:
    profiles = [serialize_profile(p) for p in report.profiles]
    recommendations = [serialize_recommendation(r) for r in report.recommendations]
    costs = [serialize_cost(c) for c in report.cost_estimates]
    avg_waste = (
        sum(p["over_provisioning_score"] for p in profiles) / len(profiles) if profiles else 0
    )
    top_saver = max(costs, key=lambda c: c["monthly_savings_usd"]) if costs else None

    under_count = sum(1 for p in profiles if p["sizing_category"] == "under-provisioned")
    right_count = sum(1 for p in profiles if p["sizing_category"] == "right-sized")
    over_count = sum(1 for p in profiles if p["sizing_category"] == "over-provisioned")

    return {
        "namespace": report.namespace,
        "total_deployments": report.total_deployments,
        "analyzed_deployments": report.analyzed_deployments,
        "total_monthly_savings_usd": report.total_monthly_savings_usd,
        "total_annual_savings_usd": report.total_annual_savings_usd,
        "generated_at": report.generated_at.isoformat(),
        "avg_waste_pct": round(avg_waste * 100, 0),
        "top_saver": top_saver,
        "under_provisioned_count": under_count,
        "right_sized_count": right_count,
        "over_provisioned_count": over_count,
        "profiles": profiles,
        "recommendations": recommendations,
        "costs": costs,
    }


def serialize_multi_cloud_summary(
    multi_costs: dict[str, list[CostEstimate]],
) -> dict:
    """Serialize multi-cloud cost estimates into a template-friendly dict.

    Returns::

        {
            "providers": {
                "aws": {"name": "AWS EKS", "total_current": ...,
                        "total_recommended": ..., "total_savings": ...},
                ...
            },
            "cheapest": "gcp",
        }
    """
    providers: dict[str, dict] = {}
    for key, estimates in multi_costs.items():
        prov = get_provider(key)
        total_current = round(sum(e.current_monthly_cost_usd for e in estimates), 2)
        total_recommended = round(sum(e.recommended_monthly_cost_usd for e in estimates), 2)
        total_savings = round(sum(e.monthly_savings_usd for e in estimates), 2)
        providers[key] = {
            "name": prov.provider_name(),
            "total_current": total_current,
            "total_recommended": total_recommended,
            "total_savings": total_savings,
        }

    cheapest = min(providers, key=lambda k: providers[k]["total_current"]) if providers else ""
    return {"providers": providers, "cheapest": cheapest}
