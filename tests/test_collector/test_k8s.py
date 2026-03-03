"""Tests for the K8sMetricsCollector (mocked Kubernetes API)."""

from __future__ import annotations

import sys
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from kube_foresight.collector.k8s import (
    _extract_deployment_name,
    _parse_cpu,
    _parse_memory,
)
from kube_foresight.exceptions import K8sMetricsError


# ── Unit parsing tests ──────────────────────────────────────────


class TestParseCpu:
    def test_millicores(self):
        assert _parse_cpu("100m") == pytest.approx(0.1)
        assert _parse_cpu("250m") == pytest.approx(0.25)
        assert _parse_cpu("1000m") == pytest.approx(1.0)

    def test_nanocores(self):
        assert _parse_cpu("100000000n") == pytest.approx(0.1)
        assert _parse_cpu("250000000n") == pytest.approx(0.25)
        assert _parse_cpu("1000000000n") == pytest.approx(1.0)

    def test_whole_cores(self):
        assert _parse_cpu("1") == pytest.approx(1.0)
        assert _parse_cpu("2") == pytest.approx(2.0)

    def test_fractional_cores(self):
        assert _parse_cpu("0.5") == pytest.approx(0.5)
        assert _parse_cpu("1.5") == pytest.approx(1.5)

    def test_whitespace(self):
        assert _parse_cpu("  100m  ") == pytest.approx(0.1)

    def test_zero(self):
        assert _parse_cpu("0") == pytest.approx(0.0)
        assert _parse_cpu("0m") == pytest.approx(0.0)
        assert _parse_cpu("0n") == pytest.approx(0.0)


class TestParseMemory:
    def test_kibibytes(self):
        assert _parse_memory("1Ki") == pytest.approx(1024.0)
        assert _parse_memory("64Ki") == pytest.approx(65536.0)

    def test_mebibytes(self):
        assert _parse_memory("128Mi") == pytest.approx(128 * 1024**2)
        assert _parse_memory("256Mi") == pytest.approx(256 * 1024**2)

    def test_gibibytes(self):
        assert _parse_memory("1Gi") == pytest.approx(1024**3)
        assert _parse_memory("2Gi") == pytest.approx(2 * 1024**3)

    def test_tebibytes(self):
        assert _parse_memory("1Ti") == pytest.approx(1024**4)

    def test_decimal_suffixes(self):
        assert _parse_memory("1k") == pytest.approx(1000.0)
        assert _parse_memory("1M") == pytest.approx(1_000_000.0)
        assert _parse_memory("1G") == pytest.approx(1_000_000_000.0)

    def test_raw_bytes(self):
        assert _parse_memory("65536") == pytest.approx(65536.0)

    def test_whitespace(self):
        assert _parse_memory("  128Mi  ") == pytest.approx(128 * 1024**2)


# ── Deployment name extraction tests ────────────────────────────


class TestExtractDeploymentName:
    def test_standard_pod_name(self):
        assert _extract_deployment_name("web-api-7d8f5b6c9d-abc12") == "web-api"

    def test_single_word_deployment(self):
        assert _extract_deployment_name("nginx-5f7b9c8d6e-xyz99") == "nginx"

    def test_multi_segment_deployment(self):
        assert _extract_deployment_name("my-cool-service-abc123-def45") == "my-cool-service"

    def test_no_match_returns_original(self):
        assert _extract_deployment_name("standalone-pod") == "standalone-pod"

    def test_single_word(self):
        assert _extract_deployment_name("redis") == "redis"


# ── Helpers ─────────────────────────────────────────────────────


def _make_pod_metric(pod_name: str, container_name: str, cpu: str, memory: str) -> dict:
    """Helper to create a pod metrics API response item."""
    return {
        "metadata": {"name": pod_name},
        "containers": [
            {
                "name": container_name,
                "usage": {"cpu": cpu, "memory": memory},
            }
        ],
    }


def _make_deployment(name: str, labels: dict) -> SimpleNamespace:
    """Helper to create a mock Deployment object."""
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name),
        spec=SimpleNamespace(
            selector=SimpleNamespace(match_labels=labels)
        ),
    )


def _make_pod(name: str, containers: list[dict] | None = None) -> SimpleNamespace:
    """Helper to create a mock Pod object."""
    if containers is None:
        containers = [{"name": "app", "cpu_req": "100m", "cpu_lim": "500m",
                        "mem_req": "128Mi", "mem_lim": "256Mi"}]
    mock_containers = []
    for c in containers:
        resources = SimpleNamespace(
            requests={"cpu": c.get("cpu_req", "0"), "memory": c.get("mem_req", "0")},
            limits={"cpu": c.get("cpu_lim", "0"), "memory": c.get("mem_lim", "0")},
        )
        mock_containers.append(
            SimpleNamespace(name=c["name"], resources=resources)
        )
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name),
        spec=SimpleNamespace(containers=mock_containers),
    )


@pytest.fixture
def mock_k8s():
    """Inject a mock 'kubernetes' package into sys.modules so deferred imports work."""
    mock_kubernetes = MagicMock()
    mock_client = MagicMock()
    mock_config = MagicMock()

    mock_kubernetes.client = mock_client
    mock_kubernetes.config = mock_config

    saved = {}
    for mod_name in ("kubernetes", "kubernetes.client", "kubernetes.config"):
        saved[mod_name] = sys.modules.get(mod_name)
        sys.modules[mod_name] = mock_kubernetes if mod_name == "kubernetes" else getattr(mock_kubernetes, mod_name.split(".")[-1])

    yield mock_client, mock_config

    # Restore original modules
    for mod_name, original in saved.items():
        if original is None:
            sys.modules.pop(mod_name, None)
        else:
            sys.modules[mod_name] = original


@pytest.fixture
def collector(tmp_path):
    """Create a K8sMetricsCollector with a temporary SQLite DB."""
    from kube_foresight.collector.k8s import K8sMetricsCollector
    return K8sMetricsCollector(db_path=tmp_path / "test.db")


# ── Collector integration tests (with mocked K8s API) ──────────


class TestK8sMetricsCollectorCheckConnection:
    def test_success(self, collector, mock_k8s):
        mock_client, _ = mock_k8s

        mock_v1 = MagicMock()
        mock_metrics = MagicMock()
        mock_client.CoreV1Api.return_value = mock_v1
        mock_client.CustomObjectsApi.return_value = mock_metrics

        collector._configured = True
        ok, msg = collector.check_connection()
        assert ok is True
        assert "connected" in msg.lower() or "metrics" in msg.lower()

    def test_import_error(self, tmp_path):
        """When kubernetes is not installed, check_connection returns False."""
        from kube_foresight.collector.k8s import K8sMetricsCollector
        c = K8sMetricsCollector(db_path=tmp_path / "test2.db")
        # Don't inject mock_k8s so the import fails naturally
        # But _ensure_k8s_client will try to import — let's patch it to raise
        with patch.object(c, "_ensure_k8s_client", side_effect=ImportError("no kubernetes")):
            ok, msg = c.check_connection()
        assert ok is False
        assert "no kubernetes" in msg


class TestK8sMetricsCollectorTakeSnapshot:
    def test_take_snapshot_writes_to_store(self, collector, mock_k8s):
        """Test that take_snapshot correctly processes pod metrics and writes to SQLite."""
        mock_client, _ = mock_k8s

        pod_metrics_response = {
            "items": [
                _make_pod_metric("web-api-abc-123", "nginx", "200m", "128Mi"),
                _make_pod_metric("worker-def-456", "worker", "500m", "256Mi"),
            ]
        }

        deploy_web = _make_deployment("web-api", {"app": "web"})
        deploy_worker = _make_deployment("worker", {"app": "worker"})

        pod_web = _make_pod("web-api-abc-123", [
            {"name": "nginx", "cpu_req": "100m", "cpu_lim": "500m",
             "mem_req": "128Mi", "mem_lim": "256Mi"}
        ])
        pod_worker = _make_pod("worker-def-456", [
            {"name": "worker", "cpu_req": "250m", "cpu_lim": "1",
             "mem_req": "256Mi", "mem_lim": "512Mi"}
        ])

        mock_metrics_api = MagicMock()
        mock_metrics_api.list_namespaced_custom_object.return_value = pod_metrics_response

        mock_core_api = MagicMock()
        mock_core_api.list_namespaced_pod.side_effect = [
            SimpleNamespace(items=[pod_web]),      # pods for web-api deployment
            SimpleNamespace(items=[pod_worker]),    # pods for worker deployment
            SimpleNamespace(items=[pod_web, pod_worker]),  # for _update_resource_specs
        ]

        mock_apps_api = MagicMock()
        mock_apps_api.list_namespaced_deployment.return_value = SimpleNamespace(
            items=[deploy_web, deploy_worker]
        )

        mock_client.CustomObjectsApi.return_value = mock_metrics_api
        mock_client.CoreV1Api.return_value = mock_core_api
        mock_client.AppsV1Api.return_value = mock_apps_api

        collector._configured = True
        count = collector.take_snapshot("default")

        assert count == 2
        assert collector.store.get_snapshot_count("default") == 2

    def test_take_snapshot_metrics_error(self, collector, mock_k8s):
        """Test that K8sMetricsError is raised when metrics API fails."""
        mock_client, _ = mock_k8s

        mock_metrics_api = MagicMock()
        mock_metrics_api.list_namespaced_custom_object.side_effect = Exception("API unavailable")

        mock_core_api = MagicMock()
        mock_apps_api = MagicMock()
        mock_apps_api.list_namespaced_deployment.return_value = SimpleNamespace(items=[])

        mock_client.CustomObjectsApi.return_value = mock_metrics_api
        mock_client.CoreV1Api.return_value = mock_core_api
        mock_client.AppsV1Api.return_value = mock_apps_api

        collector._configured = True
        with pytest.raises(K8sMetricsError, match="Failed to fetch pod metrics"):
            collector.take_snapshot("default")

    def test_take_snapshot_empty_pods(self, collector, mock_k8s):
        """Test take_snapshot with empty pod metrics response."""
        mock_client, _ = mock_k8s

        mock_metrics_api = MagicMock()
        mock_metrics_api.list_namespaced_custom_object.return_value = {"items": []}

        mock_core_api = MagicMock()
        mock_core_api.list_namespaced_pod.return_value = SimpleNamespace(items=[])

        mock_apps_api = MagicMock()
        mock_apps_api.list_namespaced_deployment.return_value = SimpleNamespace(items=[])

        mock_client.CustomObjectsApi.return_value = mock_metrics_api
        mock_client.CoreV1Api.return_value = mock_core_api
        mock_client.AppsV1Api.return_value = mock_apps_api

        collector._configured = True
        count = collector.take_snapshot("empty-ns")
        assert count == 0


class TestK8sMetricsCollectorCollect:
    def test_collect_returns_container_metrics(self, collector):
        """Test that collect() returns ContainerMetrics from stored data."""
        now_ms = int(time.time() * 1000)
        rows = []
        for i in range(5):
            ts = now_ms - (i * 300_000)
            rows.append((ts, "default", "web-abc-123", "nginx", "web", 200_000_000, 128 * 1024 * 1024))
        collector.store.insert_snapshots_batch(rows)
        collector.store.upsert_resource_spec(
            "default", "web-abc-123", "nginx", 0.5, 1.0, 256 * 1024 * 1024, 512 * 1024 * 1024,
        )

        with patch.object(collector, "take_snapshot", side_effect=Exception("no cluster")):
            metrics = collector.collect("default", lookback_hours=1, step_seconds=300)

        assert len(metrics) >= 1
        m = metrics[0]
        assert m.container_name == "nginx"
        assert m.deployment_name == "web"
        assert m.cpu_spec.request == 0.5

    def test_collect_empty_namespace(self, collector):
        """Test collect() on empty namespace returns empty list."""
        with patch.object(collector, "take_snapshot", side_effect=Exception("no cluster")):
            metrics = collector.collect("empty-ns", lookback_hours=1, step_seconds=300)
        assert metrics == []


class TestK8sMetricsCollectorBuildDeploymentMap:
    def test_builds_correct_mapping(self, collector, mock_k8s):
        """Test that _build_deployment_map returns pod->deployment mapping."""
        deploy = _make_deployment("api-server", {"app": "api"})
        pod1 = _make_pod("api-server-abc-123")
        pod2 = _make_pod("api-server-def-456")

        mock_apps_api = MagicMock()
        mock_apps_api.list_namespaced_deployment.return_value = SimpleNamespace(items=[deploy])

        mock_core_api = MagicMock()
        mock_core_api.list_namespaced_pod.return_value = SimpleNamespace(items=[pod1, pod2])

        deploy_map = collector._build_deployment_map("default", mock_core_api, mock_apps_api)

        assert deploy_map["api-server-abc-123"] == "api-server"
        assert deploy_map["api-server-def-456"] == "api-server"

    def test_empty_namespace(self, collector, mock_k8s):
        """Test deployment map with no deployments."""
        mock_apps_api = MagicMock()
        mock_apps_api.list_namespaced_deployment.return_value = SimpleNamespace(items=[])

        mock_core_api = MagicMock()

        deploy_map = collector._build_deployment_map("empty", mock_core_api, mock_apps_api)
        assert deploy_map == {}

    def test_api_failure_returns_empty_map(self, collector, mock_k8s):
        """Test that API failure falls back gracefully."""
        mock_apps_api = MagicMock()
        mock_apps_api.list_namespaced_deployment.side_effect = Exception("forbidden")

        mock_core_api = MagicMock()

        deploy_map = collector._build_deployment_map("default", mock_core_api, mock_apps_api)
        assert deploy_map == {}


class TestK8sMetricsCollectorStore:
    def test_store_property(self, collector):
        """Test that store property returns MetricsStore."""
        from kube_foresight.collector.store import MetricsStore
        assert isinstance(collector.store, MetricsStore)
