"""HPA (HorizontalPodAutoscaler) detection and conflict checking."""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger("kube_foresight.hpa")


@dataclass
class HPAInfo:
    """Summary of an HPA targeting a deployment."""

    name: str
    deployment_name: str
    namespace: str
    min_replicas: int
    max_replicas: int
    current_replicas: int
    # CPU target (percentage of request), None if not CPU-based
    cpu_target_pct: int | None
    # Memory target (percentage), None if not memory-based
    memory_target_pct: int | None


@dataclass
class HPAConflict:
    """A conflict between our recommendation and an HPA."""

    deployment_name: str
    namespace: str
    hpa_name: str
    conflict_type: str  # "cpu_target", "memory_target", "scaling_range"
    message: str


def detect_hpas(namespace: str) -> list[HPAInfo]:
    """Query the K8s API for HPAs in the given namespace."""
    try:
        from kubernetes import client, config

        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()

        autoscaling = client.AutoscalingV2Api()
        hpa_list = autoscaling.list_namespaced_horizontal_pod_autoscaler(namespace=namespace)

        results = []
        for hpa in hpa_list.items:
            # Extract target deployment name
            target = hpa.spec.scale_target_ref
            if target.kind != "Deployment":
                continue

            cpu_target = None
            mem_target = None
            for metric in (hpa.spec.metrics or []):
                if metric.type == "Resource":
                    res = metric.resource
                    if res.name == "cpu" and res.target and res.target.average_utilization:
                        cpu_target = res.target.average_utilization
                    elif res.name == "memory" and res.target and res.target.average_utilization:
                        mem_target = res.target.average_utilization

            results.append(HPAInfo(
                name=hpa.metadata.name,
                deployment_name=target.name,
                namespace=namespace,
                min_replicas=hpa.spec.min_replicas or 1,
                max_replicas=hpa.spec.max_replicas,
                current_replicas=hpa.status.current_replicas or 0,
                cpu_target_pct=cpu_target,
                memory_target_pct=mem_target,
            ))

        logger.info("Found %d HPAs in namespace '%s'", len(results), namespace)
        return results

    except ImportError:
        logger.debug("kubernetes package not available, skipping HPA detection")
        return []
    except Exception:
        logger.warning("Failed to detect HPAs", exc_info=True)
        return []


def check_hpa_conflicts(
    deployment_name: str,
    namespace: str,
    hpas: list[HPAInfo],
    recommended_cpu_request: float,
    current_cpu_request: float,
) -> list[HPAConflict]:
    """Check if our recommendation conflicts with any HPA for this deployment."""
    conflicts = []

    matching = [h for h in hpas if h.deployment_name == deployment_name]
    if not matching:
        return conflicts

    for hpa in matching:
        # If HPA targets CPU utilization and we reduce the request,
        # the utilization % goes UP, which may trigger more scaling
        if hpa.cpu_target_pct and recommended_cpu_request < current_cpu_request:
            # Example: HPA targets 80% of 500m. We recommend 200m.
            # Actual usage 100m → was 20% of 500m, now 50% of 200m.
            # HPA might scale up if usage occasionally exceeds 80% of new request.
            ratio = (
                current_cpu_request / recommended_cpu_request
                if recommended_cpu_request > 0
                else 1
            )
            if ratio > 1.5:
                conflicts.append(HPAConflict(
                    deployment_name=deployment_name,
                    namespace=namespace,
                    hpa_name=hpa.name,
                    conflict_type="cpu_target",
                    message=(
                        f"HPA '{hpa.name}' targets {hpa.cpu_target_pct}% CPU utilization. "
                        f"Reducing CPU request by {((1 - 1/ratio) * 100):.0f}% will increase "
                        f"utilization %, potentially triggering aggressive scaling "
                        f"(min={hpa.min_replicas}, max={hpa.max_replicas}). "
                        f"Consider adjusting the HPA target % after applying this patch."
                    ),
                ))

        if hpa.memory_target_pct:
            conflicts.append(HPAConflict(
                deployment_name=deployment_name,
                namespace=namespace,
                hpa_name=hpa.name,
                conflict_type="memory_target",
                message=(
                    f"HPA '{hpa.name}' scales on memory utilization "
                    f"({hpa.memory_target_pct}% target). "
                    f"Changing memory requests may affect scaling behavior."
                ),
            ))

    return conflicts
