"""Adapter: Alibaba cluster-trace-v2018 → kube-foresight ContainerMetrics.

Maps the online-service container tables of the Alibaba 2018 trace onto the
domain model the analyzer/recommender consume. Batch tables (``batch_*``) are
ignored — we only validate against long-running containers, which are the
closest analogue to Kubernetes deployments.

Trace schema (the columns we use)
---------------------------------
``machine_meta.csv``   : machine_id, time_stamp, fd1, fd2, cpu_num, mem_size, status
``container_meta.csv`` : container_id, machine_id, time_stamp, app_du, status,
                         cpu_request, cpu_limit, mem_size
``container_usage.csv``: container_id, machine_id, time_stamp, cpu_util_percent,
                         mem_util_percent, ... (further columns ignored)

Units (verified empirically against the trace)
-----------------------------------------------
* ``cpu_request``/``cpu_limit`` are in centi-cores (100 == 1 core).
* ``mem_size`` is the container's memory allocation as percent of the machine.
* ``cpu_util_percent`` / ``mem_util_percent`` are percent of the container's OWN
  allocation, NOT of the machine — both are hard-capped at 100 in the data (a
  container can't exceed its limit). So:
    usage_cpu_cores = cpu_util_percent/100 * cpu_limit_cores
    usage_mem_bytes = mem_util_percent/100 * mem_allocation_bytes
  No machine-core join is needed; CPU usage comes from the container's own limit.

``--machine-mem-gib`` only sets the absolute byte scale (the model wants memory
in bytes); it cancels out of violation-rate and savings-% — it exists so the
engine's 16Mi floor lands sensibly, not because it changes conclusions.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from kube_foresight.models import ContainerMetrics, ResourceSpec


@dataclass
class _ContainerSpec:
    app_du: str
    cpu_request: float  # cores
    cpu_limit: float  # cores
    mem_alloc_pct: float  # percent of machine memory


# Arbitrary anchor — the trace stores time as seconds from start; the absolute
# wall-clock date is irrelevant, only deltas matter.
_EPOCH = datetime(2018, 1, 1, tzinfo=timezone.utc)


def _load_container_meta(
    path: Path, max_app_groups: int | None
) -> dict[str, _ContainerSpec]:
    """Read container_meta.csv → container_id → spec.

    Limits to the first ``max_app_groups`` distinct app_du values when set, so a
    backtest can run on a slice.
    """
    specs: dict[str, _ContainerSpec] = {}
    selected_apps: set[str] = set()

    with path.open(newline="") as fh:
        for row in csv.reader(fh):
            if len(row) < 8:
                continue
            container_id, _machine, _ts, app_du = row[0], row[1], row[2], row[3]
            if not container_id:
                continue
            try:
                cpu_request = float(row[5]) / 100.0  # centi-cores → cores
                cpu_limit = float(row[6]) / 100.0
                mem_size = float(row[7])  # percent of machine memory (allocation)
            except ValueError:
                continue

            if max_app_groups is not None and app_du not in selected_apps:
                if len(selected_apps) >= max_app_groups:
                    continue
                selected_apps.add(app_du)

            specs[container_id] = _ContainerSpec(
                app_du=app_du,
                cpu_request=cpu_request,
                cpu_limit=cpu_limit if cpu_limit > 0 else cpu_request,
                mem_alloc_pct=mem_size,
            )

    return specs


def load_alibaba_trace(
    trace_dir: str | Path,
    *,
    max_app_groups: int | None = 200,
    machine_mem_gib: float = 96.0,
    max_usage_rows: int | None = None,
) -> list[ContainerMetrics]:
    """Build ContainerMetrics from an Alibaba v2018 trace directory.

    Args:
        trace_dir: directory containing container_meta.csv and container_usage.csv.
        max_app_groups: cap on distinct app_du groups to keep (sampling). None = all.
        machine_mem_gib: assumed host memory, used only to express the
            percent-of-machine memory figures as bytes for the model.
        max_usage_rows: stop after this many usage rows (smoke-test guard). None = all.

    Each app_du becomes a deployment; each container becomes a replica.
    """
    trace_dir = Path(trace_dir)
    specs = _load_container_meta(trace_dir / "container_meta.csv", max_app_groups)
    mem_bytes_per_pct = machine_mem_gib * (1024**3) / 100.0

    cpu_series: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    mem_series: dict[str, list[tuple[datetime, float]]] = defaultdict(list)

    with (trace_dir / "container_usage.csv").open(newline="") as fh:
        for i, row in enumerate(csv.reader(fh)):
            if max_usage_rows is not None and i >= max_usage_rows:
                break
            if len(row) < 5:
                continue
            container_id = row[0]
            spec = specs.get(container_id)
            if spec is None:
                continue  # not in the sampled slice / a batch row / empty id
            try:
                ts = _EPOCH + timedelta(seconds=float(row[2]))
                cpu_pct = float(row[3])
                mem_pct = float(row[4])
            except ValueError:
                continue
            # util% is percent of the container's own allocation, not the machine.
            cpu_series[container_id].append((ts, cpu_pct / 100.0 * spec.cpu_limit))
            mem_alloc_bytes = spec.mem_alloc_pct * mem_bytes_per_pct
            mem_series[container_id].append((ts, mem_pct / 100.0 * mem_alloc_bytes))

    results: list[ContainerMetrics] = []
    for container_id, spec in specs.items():
        cpu = sorted(cpu_series.get(container_id, []))
        mem = sorted(mem_series.get(container_id, []))
        if not cpu or not mem:
            continue
        # mem_size is both the request and the hard cap (OOM ceiling).
        mem_alloc_bytes = spec.mem_alloc_pct * mem_bytes_per_pct
        results.append(
            ContainerMetrics(
                container_name=spec.app_du,
                pod_name=container_id,
                deployment_name=spec.app_du,
                namespace="alibaba-2018",
                cpu_usage=cpu,
                memory_usage=mem,
                cpu_spec=ResourceSpec(request=spec.cpu_request, limit=spec.cpu_limit),
                memory_spec=ResourceSpec(request=mem_alloc_bytes, limit=mem_alloc_bytes),
            )
        )
    return results
