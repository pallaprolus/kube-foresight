"""Deployment profiling and over-provisioning detection."""

from __future__ import annotations

from kube_foresight.analyzer.stats import aggregate_deployment_metrics, compute_usage_stats
from kube_foresight.models import ContainerMetrics, DeploymentProfile


def compute_over_provisioning_score(
    cpu_utilization_ratio: float,
    memory_utilization_ratio: float,
) -> float:
    """Compute composite over-provisioning score.

    CPU weight: 0.6, Memory weight: 0.4.
    Higher score = more over-provisioned. Clamped to [0, 1].
    """
    cpu_waste = max(0.0, 1.0 - cpu_utilization_ratio)
    mem_waste = max(0.0, 1.0 - memory_utilization_ratio)
    return min(1.0, 0.6 * cpu_waste + 0.4 * mem_waste)


def profile_deployments(
    container_metrics: list[ContainerMetrics],
) -> list[DeploymentProfile]:
    """Build deployment profiles from container metrics."""
    grouped = aggregate_deployment_metrics(container_metrics)
    profiles: list[DeploymentProfile] = []

    for deploy_name, containers in grouped.items():
        # Aggregate CPU and memory values across all pods/containers
        all_cpu_values: list[float] = []
        all_mem_values: list[float] = []
        for cm in containers:
            all_cpu_values.extend(v for _, v in cm.cpu_usage)
            all_mem_values.extend(v for _, v in cm.memory_usage)

        if not all_cpu_values or not all_mem_values:
            continue

        cpu_stats = compute_usage_stats(all_cpu_values)
        mem_stats = compute_usage_stats(all_mem_values)

        # Use the first container's spec (all replicas share the same spec)
        container_name = containers[0].container_name
        cpu_spec = containers[0].cpu_spec
        mem_spec = containers[0].memory_spec
        namespace = containers[0].namespace

        # Count unique pods as replica count
        replica_count = len({cm.pod_name for cm in containers})

        cpu_util = cpu_stats.mean / cpu_spec.request if cpu_spec.request > 0 else 1.0
        mem_util = mem_stats.mean / mem_spec.request if mem_spec.request > 0 else 1.0

        profiles.append(
            DeploymentProfile(
                name=deploy_name,
                container_name=container_name,
                namespace=namespace,
                replica_count=replica_count,
                cpu_stats=cpu_stats,
                memory_stats=mem_stats,
                cpu_spec=cpu_spec,
                memory_spec=mem_spec,
                cpu_utilization_ratio=cpu_util,
                memory_utilization_ratio=mem_util,
                over_provisioning_score=compute_over_provisioning_score(cpu_util, mem_util),
            )
        )

    return profiles


def rank_by_over_provisioning(
    profiles: list[DeploymentProfile],
    top_n: int = 10,
) -> list[DeploymentProfile]:
    """Sort profiles by over-provisioning score (descending) and return top N."""
    return sorted(profiles, key=lambda p: p.over_provisioning_score, reverse=True)[:top_n]
