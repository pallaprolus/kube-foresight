"""Convert domain dataclasses to JSON-safe dicts for API responses and templates."""

from __future__ import annotations

from kube_foresight.models import (
    AnalysisReport,
    CostEstimate,
    DeploymentProfile,
    Recommendation,
)
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


def serialize_report(report: AnalysisReport) -> dict:
    profiles = [serialize_profile(p) for p in report.profiles]
    recommendations = [serialize_recommendation(r) for r in report.recommendations]
    costs = [serialize_cost(c) for c in report.cost_estimates]
    avg_waste = (
        sum(p["over_provisioning_score"] for p in profiles) / len(profiles) if profiles else 0
    )
    top_saver = max(costs, key=lambda c: c["monthly_savings_usd"]) if costs else None
    return {
        "namespace": report.namespace,
        "total_deployments": report.total_deployments,
        "analyzed_deployments": report.analyzed_deployments,
        "total_monthly_savings_usd": report.total_monthly_savings_usd,
        "total_annual_savings_usd": report.total_annual_savings_usd,
        "generated_at": report.generated_at.isoformat(),
        "avg_waste_pct": round(avg_waste * 100, 0),
        "top_saver": top_saver,
        "profiles": profiles,
        "recommendations": recommendations,
        "costs": costs,
    }
