"""Recommendation engine — orchestrates right-sizing across deployments."""

from __future__ import annotations

from kube_foresight.models import DeploymentProfile, Recommendation, SizingCategory
from kube_foresight.recommender.strategies import determine_confidence, recommend_by_percentile

# Minimum floors: 10m CPU, 16Mi memory
_CPU_FLOOR = 0.01
_MEM_FLOOR = 16 * 1024 * 1024


def generate_recommendations(
    profiles: list[DeploymentProfile],
    strategy: str = "p95",
    headroom: float = 0.20,
) -> list[Recommendation]:
    """Generate right-sizing recommendations for a list of deployment profiles."""
    recommendations: list[Recommendation] = []

    for profile in profiles:
        # Skip right-sized deployments — no recommendation needed
        if profile.sizing_category == SizingCategory.RIGHT_SIZED:
            continue

        direction = (
            "up" if profile.sizing_category == SizingCategory.UNDER_PROVISIONED else "down"
        )

        rec_cpu_req, rec_cpu_lim = recommend_by_percentile(
            stats=profile.cpu_stats,
            current_request=profile.cpu_spec.request,
            current_limit=profile.cpu_spec.limit,
            percentile=strategy,
            headroom=headroom,
            floor=_CPU_FLOOR,
            direction=direction,
        )
        rec_mem_req, rec_mem_lim = recommend_by_percentile(
            stats=profile.memory_stats,
            current_request=profile.memory_spec.request,
            current_limit=profile.memory_spec.limit,
            percentile=strategy,
            headroom=headroom,
            floor=_MEM_FLOOR,
            direction=direction,
        )

        cpu_reduction = (
            (1 - rec_cpu_req / profile.cpu_spec.request) * 100
            if profile.cpu_spec.request > 0
            else 0.0
        )
        mem_reduction = (
            (1 - rec_mem_req / profile.memory_spec.request) * 100
            if profile.memory_spec.request > 0
            else 0.0
        )

        # Use the lower confidence of CPU and memory
        cpu_conf = determine_confidence(profile.cpu_stats)
        mem_conf = determine_confidence(profile.memory_stats)
        confidence = min(cpu_conf, mem_conf, key=lambda c: ["high", "medium", "low"].index(c.value))

        recommendations.append(
            Recommendation(
                deployment_name=profile.name,
                container_name=profile.container_name,
                namespace=profile.namespace,
                strategy=strategy,
                headroom=headroom,
                current_cpu_request=profile.cpu_spec.request,
                current_cpu_limit=profile.cpu_spec.limit,
                current_memory_request=profile.memory_spec.request,
                current_memory_limit=profile.memory_spec.limit,
                recommended_cpu_request=rec_cpu_req,
                recommended_cpu_limit=rec_cpu_lim,
                recommended_memory_request=rec_mem_req,
                recommended_memory_limit=rec_mem_lim,
                cpu_reduction_pct=round(cpu_reduction, 1),
                memory_reduction_pct=round(mem_reduction, 1),
                confidence=confidence,
            )
        )

    return recommendations
