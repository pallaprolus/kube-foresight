"""Mock collector that generates synthetic Kubernetes workload data."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

from kube_foresight.collector.base import BaseCollector
from kube_foresight.models import ContainerMetrics, ResourceSpec

# (cpu_request, mem_request_bytes, cpu_base_usage, mem_base_usage_bytes, pattern, replicas)
_MiB = 1024 * 1024
DEPLOYMENT_PROFILES: dict[str, tuple[float, float, float, float, str, int]] = {
    "api-gateway": (1.0, 1024 * _MiB, 0.08, 120 * _MiB, "diurnal", 3),
    "user-service": (0.5, 512 * _MiB, 0.04, 64 * _MiB, "steady", 2),
    "payment-processor": (0.5, 512 * _MiB, 0.35, 380 * _MiB, "bursty", 2),
    "notification-svc": (0.25, 256 * _MiB, 0.02, 32 * _MiB, "steady", 1),
    "data-pipeline": (2.0, 2048 * _MiB, 0.15, 256 * _MiB, "diurnal", 2),
    "auth-service": (0.5, 512 * _MiB, 0.05, 80 * _MiB, "diurnal", 3),
    "frontend": (0.5, 512 * _MiB, 0.12, 200 * _MiB, "diurnal", 4),
    "cache-warmer": (1.0, 1024 * _MiB, 0.06, 100 * _MiB, "steady", 1),
    "log-aggregator": (1.0, 2048 * _MiB, 0.10, 180 * _MiB, "growing", 2),
    "metrics-exporter": (0.25, 256 * _MiB, 0.03, 40 * _MiB, "steady", 1),
    "order-service": (0.5, 512 * _MiB, 0.08, 90 * _MiB, "diurnal", 3),
    "inventory-service": (0.5, 512 * _MiB, 0.06, 70 * _MiB, "steady", 2),
    "search-indexer": (1.0, 1024 * _MiB, 0.30, 600 * _MiB, "bursty", 2),
    "email-worker": (0.25, 256 * _MiB, 0.02, 30 * _MiB, "steady", 1),
    "report-generator": (2.0, 4096 * _MiB, 0.10, 200 * _MiB, "bursty", 1),
}


class MockCollector(BaseCollector):
    """Generates synthetic Kubernetes resource metrics for demonstration."""

    def __init__(self, seed: int = 42) -> None:
        self._rng = np.random.default_rng(seed)

    def check_connection(self) -> tuple[bool, str]:
        return True, "Mock collector (synthetic data)"

    def list_namespaces(self) -> list[str]:
        return ["demo-app"]

    def collect(
        self,
        namespace: str = "demo-app",
        lookback_hours: int = 168,
        step_seconds: int = 300,
    ) -> list[ContainerMetrics]:
        n_points = (lookback_hours * 3600) // step_seconds
        now = datetime.now(timezone.utc)
        timestamps = [
            now - timedelta(seconds=step_seconds * (n_points - i)) for i in range(n_points)
        ]

        results: list[ContainerMetrics] = []
        for deploy_name, profile in DEPLOYMENT_PROFILES.items():
            cpu_req, mem_req, cpu_base, mem_base, pattern, replicas = profile

            for replica_idx in range(replicas):
                pod_name = f"{deploy_name}-{self._random_hash()}-{self._random_hash(5)}"

                cpu_values = self._generate_series(cpu_base, pattern, n_points, noise_pct=0.1)
                mem_values = self._generate_series(mem_base, pattern, n_points, noise_pct=0.05)

                results.append(
                    ContainerMetrics(
                        container_name=deploy_name,
                        pod_name=pod_name,
                        deployment_name=deploy_name,
                        namespace=namespace,
                        cpu_usage=list(zip(timestamps, cpu_values.tolist())),
                        memory_usage=list(zip(timestamps, mem_values.tolist())),
                        cpu_spec=ResourceSpec(request=cpu_req, limit=cpu_req * 2),
                        memory_spec=ResourceSpec(request=mem_req, limit=mem_req * 2),
                    )
                )

        return results

    def _generate_series(
        self, base: float, pattern: str, n_points: int, noise_pct: float = 0.1
    ) -> np.ndarray:
        t = np.arange(n_points)
        points_per_day = (24 * 3600) // 300  # 288

        if pattern == "steady":
            values = np.full(n_points, base)
        elif pattern == "diurnal":
            daily_phase = (t % points_per_day) / points_per_day
            values = base * (1 + 0.4 * np.sin(2 * np.pi * daily_phase - np.pi / 2))
        elif pattern == "bursty":
            values = np.full(n_points, base * 0.3)
            spike_mask = self._rng.random(n_points) < 0.02
            n_spikes = spike_mask.sum()
            if n_spikes > 0:
                values[spike_mask] = base * self._rng.uniform(2, 5, n_spikes)
        elif pattern == "growing":
            values = base * (1 + 0.5 * t / n_points)
        else:
            values = np.full(n_points, base)

        noise = self._rng.normal(0, base * noise_pct, n_points)
        values = np.maximum(values + noise, 0)
        return values

    def _random_hash(self, length: int = 10) -> str:
        chars = "abcdefghijklmnopqrstuvwxyz0123456789"
        return "".join(self._rng.choice(list(chars), size=length))
