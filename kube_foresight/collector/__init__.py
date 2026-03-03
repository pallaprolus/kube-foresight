"""Metric collectors for kube-foresight."""

from __future__ import annotations

from kube_foresight.collector.base import BaseCollector
from kube_foresight.collector.mock import MockCollector


def get_collector(
    mode: str = "prometheus",
    prometheus_url: str | None = None,
    seed: int = 42,
    **kwargs,
) -> BaseCollector:
    """Factory: returns the appropriate collector."""
    if mode == "mock":
        return MockCollector(seed=seed)

    if mode == "k8s":
        from kube_foresight.collector.k8s import K8sMetricsCollector

        return K8sMetricsCollector(
            db_path=kwargs.get("db_path"),
            kubeconfig=kwargs.get("kubeconfig"),
            context=kwargs.get("context"),
        )

    from kube_foresight.collector.prometheus import PrometheusCollector

    if not prometheus_url:
        raise ValueError("prometheus_url required for prometheus mode")
    return PrometheusCollector(url=prometheus_url, **kwargs)
