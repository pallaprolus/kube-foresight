"""Kubernetes Metrics API collector with SQLite-backed historical storage."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from kube_foresight.collector.base import BaseCollector
from kube_foresight.collector.store import MetricsStore
from kube_foresight.exceptions import K8sConnectionError, K8sMetricsError
from kube_foresight.models import ContainerMetrics

logger = logging.getLogger(__name__)

# ── Unit parsers ──────────────────────────────────────────────────

_MEMORY_SUFFIXES: dict[str, int] = {
    "Ki": 1024,
    "Mi": 1024**2,
    "Gi": 1024**3,
    "Ti": 1024**4,
    "k": 1000,
    "M": 1000**2,
    "G": 1000**3,
    "T": 1000**4,
}


def _parse_cpu(value: str) -> float:
    """Parse CPU string to cores (float).

    Formats: "100m" → 0.1, "250000000n" → 0.25, "0.5" → 0.5, "1" → 1.0
    """
    value = value.strip()
    if value.endswith("n"):
        return int(value[:-1]) / 1_000_000_000
    if value.endswith("m"):
        return int(value[:-1]) / 1_000
    return float(value)


def _parse_memory(value: str) -> float:
    """Parse memory string to bytes (float).

    Formats: "128Mi" → 134217728.0, "1Gi" → 1073741824.0, "65536" → 65536.0
    """
    value = value.strip()
    for suffix, multiplier in _MEMORY_SUFFIXES.items():
        if value.endswith(suffix):
            return float(value[: -len(suffix)]) * multiplier
    return float(value)


_DEPLOY_RE = re.compile(r"^(.+)-[a-z0-9]+-[a-z0-9]+$")


def _extract_deployment_name(pod_name: str) -> str:
    """Extract deployment name from pod name using regex fallback."""
    m = _DEPLOY_RE.match(pod_name)
    return m.group(1) if m else pod_name


# ── Collector ─────────────────────────────────────────────────────


class K8sMetricsCollector(BaseCollector):
    """Collects metrics from the Kubernetes Metrics API and stores them in SQLite."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        kubeconfig: str | None = None,
        context: str | None = None,
    ) -> None:
        self._store = MetricsStore(db_path=db_path)
        self._kubeconfig = kubeconfig
        self._context = context
        self._configured = False

    def _ensure_k8s_client(self) -> None:
        """Lazily load and configure the kubernetes client."""
        if self._configured:
            return
        try:
            from kubernetes import config  # type: ignore[import-untyped]
        except ImportError:
            raise ImportError(
                "The 'kubernetes' package is required for K8s metrics collection.\n"
                'Install it with: pip install -e ".[k8s]"'
            )
        try:
            config.load_incluster_config()
            logger.info("Loaded in-cluster Kubernetes config")
        except config.ConfigException:
            config.load_kube_config(
                config_file=self._kubeconfig,
                context=self._context,
            )
            logger.info("Loaded kubeconfig")
        self._configured = True

    def check_connection(self) -> tuple[bool, str]:
        """Verify Kubernetes API and metrics-server are reachable."""
        try:
            self._ensure_k8s_client()
            from kubernetes import client  # type: ignore[import-untyped]

            # Check basic API connectivity
            v1 = client.CoreV1Api()
            v1.list_namespace(limit=1)

            # Check metrics-server
            metrics_api = client.CustomObjectsApi()
            metrics_api.list_cluster_custom_object(
                group="metrics.k8s.io",
                version="v1beta1",
                plural="nodes",
            )

            return True, "Connected to Kubernetes cluster with metrics-server"
        except ImportError as e:
            return False, str(e)
        except Exception as e:
            return False, f"Kubernetes connection failed: {e}"

    def take_snapshot(self, namespace: str) -> int:
        """Fetch current pod metrics and resource specs, write to SQLite.

        Returns the number of container metric points written.
        """
        self._ensure_k8s_client()
        from kubernetes import client  # type: ignore[import-untyped]

        metrics_api = client.CustomObjectsApi()
        core_api = client.CoreV1Api()
        apps_api = client.AppsV1Api()

        now_ms = int(time.time() * 1000)

        # 1. Build deployment mapping: pod_name → deployment_name
        deploy_map = self._build_deployment_map(namespace, core_api, apps_api)

        # 2. Fetch pod metrics from metrics-server
        try:
            pod_metrics = metrics_api.list_namespaced_custom_object(
                group="metrics.k8s.io",
                version="v1beta1",
                namespace=namespace,
                plural="pods",
            )
        except Exception as e:
            raise K8sMetricsError(f"Failed to fetch pod metrics: {e}")

        # 3. Process metrics and write to store
        rows: list[tuple[int, str, str, str, str, int, int]] = []
        for pod_metric in pod_metrics.get("items", []):
            pod_name = pod_metric["metadata"]["name"]
            deployment_name = deploy_map.get(pod_name, _extract_deployment_name(pod_name))

            for container in pod_metric.get("containers", []):
                container_name = container["name"]
                cpu_str = container["usage"].get("cpu", "0")
                mem_str = container["usage"].get("memory", "0")
                cpu_nanocores = int(_parse_cpu(cpu_str) * 1_000_000_000)
                memory_bytes = int(_parse_memory(mem_str))

                rows.append((
                    now_ms, namespace, pod_name, container_name,
                    deployment_name, cpu_nanocores, memory_bytes,
                ))

        if rows:
            self._store.insert_snapshots_batch(rows)

        # 4. Fetch and store resource specs from pod definitions
        self._update_resource_specs(namespace, core_api, deploy_map)

        logger.info("Snapshot: %d container metrics in namespace '%s'", len(rows), namespace)
        return len(rows)

    def _build_deployment_map(
        self,
        namespace: str,
        core_api: object,
        apps_api: object,
    ) -> dict[str, str]:
        """Map pod names to deployment names via the API chain."""
        from kubernetes import client  # type: ignore[import-untyped]

        deploy_map: dict[str, str] = {}
        try:
            # Get all deployments and their selectors
            deployments = apps_api.list_namespaced_deployment(namespace=namespace)  # type: ignore[union-attr]
            for deploy in deployments.items:
                selector = deploy.spec.selector.match_labels
                if not selector:
                    continue
                selector_str = ",".join(f"{k}={v}" for k, v in selector.items())
                # List pods matching this deployment's selector
                pods = core_api.list_namespaced_pod(  # type: ignore[union-attr]
                    namespace=namespace,
                    label_selector=selector_str,
                )
                for pod in pods.items:
                    deploy_map[pod.metadata.name] = deploy.metadata.name
        except Exception as e:
            logger.warning("Could not build deployment map via API, falling back to regex: %s", e)

        return deploy_map

    def _update_resource_specs(
        self,
        namespace: str,
        core_api: object,
        deploy_map: dict[str, str],
    ) -> None:
        """Read resource requests/limits from pod specs and store them."""
        try:
            pods = core_api.list_namespaced_pod(namespace=namespace)  # type: ignore[union-attr]
            for pod in pods.items:
                pod_name = pod.metadata.name
                for container in pod.spec.containers:
                    resources = container.resources or type("R", (), {"requests": None, "limits": None})()
                    requests = resources.requests or {}
                    limits = resources.limits or {}

                    cpu_req = _parse_cpu(requests.get("cpu", "0"))
                    cpu_lim = _parse_cpu(limits.get("cpu", "0"))
                    mem_req = _parse_memory(requests.get("memory", "0"))
                    mem_lim = _parse_memory(limits.get("memory", "0"))

                    # Default: limit = 2x request if not set
                    if cpu_lim == 0 and cpu_req > 0:
                        cpu_lim = cpu_req * 2
                    if mem_lim == 0 and mem_req > 0:
                        mem_lim = mem_req * 2

                    if cpu_req > 0 or mem_req > 0:
                        self._store.upsert_resource_spec(
                            namespace, pod_name, container.name,
                            cpu_req, cpu_lim, mem_req, mem_lim,
                        )
        except Exception as e:
            logger.warning("Could not update resource specs: %s", e)

    def collect(
        self,
        namespace: str,
        lookback_hours: int = 168,
        step_seconds: int = 300,
    ) -> list[ContainerMetrics]:
        """Collect historical metrics from SQLite store.

        Takes a best-effort snapshot first (if K8s API is reachable),
        then reads the stored time-series data.
        """
        # Best-effort: take a fresh snapshot
        try:
            self.take_snapshot(namespace)
        except Exception as e:
            logger.warning("Could not take fresh snapshot (using stored data): %s", e)

        return self._store.query_timeseries(
            namespace=namespace,
            lookback_hours=lookback_hours,
            step_seconds=step_seconds,
        )

    @property
    def store(self) -> MetricsStore:
        """Expose the store for direct access (e.g., from the collect CLI)."""
        return self._store
