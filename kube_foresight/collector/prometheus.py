"""Prometheus collector — fetches real metrics via the Prometheus HTTP API."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import requests

from kube_foresight.collector.base import BaseCollector
from kube_foresight.exceptions import PrometheusConnectionError, PrometheusQueryError
from kube_foresight.models import ContainerMetrics, ResourceSpec


class PrometheusCollector(BaseCollector):
    """Collects Kubernetes resource metrics from a Prometheus instance."""

    def __init__(
        self,
        url: str,
        bearer_token: str | None = None,
        basic_auth: tuple[str, str] | None = None,
        timeout: int = 30,
    ) -> None:
        self._url = url.rstrip("/")
        self._timeout = timeout
        self._session = requests.Session()
        if bearer_token:
            self._session.headers["Authorization"] = f"Bearer {bearer_token}"
        if basic_auth:
            self._session.auth = basic_auth

    def check_connection(self) -> tuple[bool, str]:
        try:
            resp = self._session.get(
                f"{self._url}/api/v1/status/buildinfo", timeout=self._timeout
            )
            if resp.status_code == 200:
                version = resp.json().get("data", {}).get("version", "unknown")
                return True, f"Connected to Prometheus {version}"
            return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
        except requests.ConnectionError as e:
            return False, f"Connection error: {e}"
        except Exception as e:
            return False, f"Error: {e}"

    def collect(
        self,
        namespace: str,
        lookback_hours: int = 168,
        step_seconds: int = 300,
    ) -> list[ContainerMetrics]:
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=lookback_hours)

        # Fetch all required metrics
        cpu_usage = self._query_range(
            f'rate(container_cpu_usage_seconds_total{{namespace="{namespace}",'
            f'container!="POD",container!=""}}[5m])',
            start, end, step_seconds,
        )
        mem_usage = self._query_range(
            f'container_memory_working_set_bytes{{namespace="{namespace}",'
            f'container!="POD",container!=""}}',
            start, end, step_seconds,
        )
        cpu_requests = self._query_instant(
            f'kube_pod_container_resource_requests{{namespace="{namespace}",resource="cpu"}}'
        )
        cpu_limits = self._query_instant(
            f'kube_pod_container_resource_limits{{namespace="{namespace}",resource="cpu"}}'
        )
        mem_requests = self._query_instant(
            f'kube_pod_container_resource_requests{{namespace="{namespace}",resource="memory"}}'
        )
        mem_limits = self._query_instant(
            f'kube_pod_container_resource_limits{{namespace="{namespace}",resource="memory"}}'
        )

        # Index resource specs by (pod, container)
        def _spec_key(labels: dict) -> str:
            return f"{labels.get('pod', '')}:{labels.get('container', '')}"

        cpu_req_map = {_spec_key(r["metric"]): float(r["value"][1]) for r in cpu_requests}
        cpu_lim_map = {_spec_key(r["metric"]): float(r["value"][1]) for r in cpu_limits}
        mem_req_map = {_spec_key(r["metric"]): float(r["value"][1]) for r in mem_requests}
        mem_lim_map = {_spec_key(r["metric"]): float(r["value"][1]) for r in mem_limits}

        # Index usage series by (pod, container)
        cpu_series: dict[str, list[tuple[datetime, float]]] = {}
        for result in cpu_usage:
            key = _spec_key(result["metric"])
            cpu_series[key] = [
                (datetime.fromtimestamp(ts, tz=timezone.utc), float(val))
                for ts, val in result["values"]
            ]

        mem_series: dict[str, list[tuple[datetime, float]]] = {}
        for result in mem_usage:
            key = _spec_key(result["metric"])
            mem_series[key] = [
                (datetime.fromtimestamp(ts, tz=timezone.utc), float(val))
                for ts, val in result["values"]
            ]

        # Join into ContainerMetrics
        results: list[ContainerMetrics] = []
        all_keys = set(cpu_series.keys()) & set(mem_series.keys())

        for key in all_keys:
            parts = key.split(":", 1)
            if len(parts) != 2:
                continue
            pod_name, container_name = parts
            deployment_name = _extract_deployment_name(pod_name)

            cpu_req = cpu_req_map.get(key, 0.0)
            cpu_lim = cpu_lim_map.get(key, cpu_req * 2)
            mem_req = mem_req_map.get(key, 0.0)
            mem_lim = mem_lim_map.get(key, mem_req * 2)

            if cpu_req == 0 and mem_req == 0:
                continue

            results.append(
                ContainerMetrics(
                    container_name=container_name,
                    pod_name=pod_name,
                    deployment_name=deployment_name,
                    namespace=namespace,
                    cpu_usage=cpu_series[key],
                    memory_usage=mem_series[key],
                    cpu_spec=ResourceSpec(request=cpu_req, limit=cpu_lim),
                    memory_spec=ResourceSpec(request=mem_req, limit=mem_lim),
                )
            )

        return results

    def _query_range(
        self, query: str, start: datetime, end: datetime, step: int
    ) -> list[dict]:
        """Execute a Prometheus range query."""
        try:
            resp = self._session.get(
                f"{self._url}/api/v1/query_range",
                params={
                    "query": query,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "step": f"{step}s",
                },
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") != "success":
                raise PrometheusQueryError(f"Query failed: {data.get('error', 'unknown')}")
            return data.get("data", {}).get("result", [])
        except requests.ConnectionError as e:
            raise PrometheusConnectionError(f"Connection error: {e}") from e
        except requests.HTTPError as e:
            raise PrometheusQueryError(f"HTTP error: {e}") from e

    def _query_instant(self, query: str) -> list[dict]:
        """Execute a Prometheus instant query."""
        try:
            resp = self._session.get(
                f"{self._url}/api/v1/query",
                params={"query": query},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") != "success":
                raise PrometheusQueryError(f"Query failed: {data.get('error', 'unknown')}")
            return data.get("data", {}).get("result", [])
        except requests.ConnectionError as e:
            raise PrometheusConnectionError(f"Connection error: {e}") from e
        except requests.HTTPError as e:
            raise PrometheusQueryError(f"HTTP error: {e}") from e


def _extract_deployment_name(pod_name: str) -> str:
    """Extract deployment name from pod name.

    Pod names follow the pattern: <deployment>-<replicaset-hash>-<pod-hash>
    e.g., api-gateway-7d5f8c6b9-xk2pq -> api-gateway
    """
    match = re.match(r"^(.+)-[a-z0-9]+-[a-z0-9]+$", pod_name)
    if match:
        return match.group(1)
    # Fallback: strip last two segments
    parts = pod_name.rsplit("-", 2)
    if len(parts) >= 3:
        return "-".join(parts[:-2])
    return pod_name
