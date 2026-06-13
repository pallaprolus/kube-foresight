"""Recommendation engine — orchestrates right-sizing across deployments."""

from __future__ import annotations

from kube_foresight.models import DeploymentProfile, Recommendation, ResourceSpec, UsageStats
from kube_foresight.recommender.strategies import determine_confidence, recommend_by_percentile

# Minimum floors: 10m CPU, 16Mi memory
_CPU_FLOOR = 0.01
_MEM_FLOOR = 16 * 1024 * 1024

# p95-utilization thresholds (match analyzer.profiler.classify_sizing):
# below this fraction of request → over-provisioned, above → under-provisioned.
_OVER_THRESHOLD = 0.3
_UNDER_THRESHOLD = 0.8


def _resource_direction(p95: float, request: float) -> str:
    """Decide sizing direction for a single resource from its p95 utilization.

    CPU and memory are sized independently — a deployment can be wasteful on CPU
    while pinned at its memory limit, and each resource should be addressed on
    its own merits rather than forced to share one deployment-wide direction.
    """
    if request <= 0:
        return "hold"
    ratio = p95 / request
    if ratio < _OVER_THRESHOLD:
        return "down"
    if ratio > _UNDER_THRESHOLD:
        return "up"
    return "hold"


def _size_resource(
    direction: str,
    stats: UsageStats,
    spec: ResourceSpec,
    strategy: str,
    headroom: float,
    floor: float,
) -> tuple[float, float]:
    """Recommended (request, limit) for one resource; unchanged when held."""
    if direction == "hold":
        return spec.request, spec.limit
    return recommend_by_percentile(
        stats=stats,
        current_request=spec.request,
        current_limit=spec.limit,
        percentile=strategy,
        headroom=headroom,
        floor=floor,
        direction=direction,
    )


def generate_recommendations(
    profiles: list[DeploymentProfile],
    strategy: str = "p95",
    headroom: float = 0.20,
) -> list[Recommendation]:
    """Generate right-sizing recommendations for a list of deployment profiles."""
    recommendations: list[Recommendation] = []

    for profile in profiles:
        cpu_dir = _resource_direction(profile.cpu_stats.p95, profile.cpu_spec.request)
        mem_dir = _resource_direction(profile.memory_stats.p95, profile.memory_spec.request)

        # Skip only when BOTH resources are already right-sized.
        if cpu_dir == "hold" and mem_dir == "hold":
            continue

        rec_cpu_req, rec_cpu_lim = _size_resource(
            cpu_dir, profile.cpu_stats, profile.cpu_spec, strategy, headroom, _CPU_FLOOR
        )
        rec_mem_req, rec_mem_lim = _size_resource(
            mem_dir, profile.memory_stats, profile.memory_spec, strategy, headroom, _MEM_FLOOR
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
