"""Kubernetes YAML patch generation."""

from __future__ import annotations

import math
from pathlib import Path

import yaml

from kube_foresight.models import Recommendation


def format_cpu(cores: float) -> str:
    """Format CPU cores as Kubernetes resource string.

    Examples: 0.1 -> "100m", 1.5 -> "1500m", 2.0 -> "2"
    """
    if cores >= 1.0 and cores == int(cores):
        return str(int(cores))
    return f"{int(round(cores * 1000))}m"


def format_memory(bytes_val: float) -> str:
    """Format memory bytes as Kubernetes resource string.

    Examples: 67108864 -> "64Mi", 1073741824 -> "1Gi"
    """
    gib = bytes_val / (1024**3)
    if gib >= 1.0 and gib == math.floor(gib):
        return f"{int(gib)}Gi"
    mib = bytes_val / (1024**2)
    return f"{int(round(mib))}Mi"


def generate_patch(recommendation: Recommendation) -> dict:
    """Generate a Kubernetes strategic merge patch dict for a deployment."""
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": recommendation.deployment_name,
            "namespace": recommendation.namespace,
        },
        "spec": {
            "template": {
                "spec": {
                    "containers": [
                        {
                            "name": recommendation.container_name,
                            "resources": {
                                "requests": {
                                    "cpu": format_cpu(recommendation.recommended_cpu_request),
                                    "memory": format_memory(
                                        recommendation.recommended_memory_request
                                    ),
                                },
                                "limits": {
                                    "cpu": format_cpu(recommendation.recommended_cpu_limit),
                                    "memory": format_memory(
                                        recommendation.recommended_memory_limit
                                    ),
                                },
                            },
                        }
                    ]
                }
            }
        },
    }


def write_patches(
    recommendations: list[Recommendation],
    output_dir: str = "./patches",
) -> list[str]:
    """Write YAML patch files to disk. Returns list of written file paths."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    for rec in recommendations:
        patch = generate_patch(rec)
        file_path = out / f"{rec.deployment_name}-patch.yaml"
        with open(file_path, "w") as f:
            yaml.dump(patch, f, default_flow_style=False, sort_keys=False)
        written.append(str(file_path))

    return written
