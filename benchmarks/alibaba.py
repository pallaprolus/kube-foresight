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

Units & the one assumption that matters
---------------------------------------
* ``cpu_request``/``cpu_limit`` are in centi-cores (100 == 1 core).
* ``mem_size`` (request) and ``mem_util_percent`` (usage) are BOTH percent of
  machine memory, so memory ratios are correct without any absolute scale.
* ``cpu_util_percent`` (usage) is percent of the *machine's* CPU, so converting
  it to cores requires the machine core count from ``machine_meta.cpu_num``.
  This is the one join that genuinely affects CPU numbers — without the true
  core count, CPU usage/request ratios would be wrong. Memory needs no such join.

``--machine-mem-gib`` only sets the absolute byte scale (the model wants memory
in bytes); it cancels out of violation-rate and savings-% — it exists so the
engine's 16Mi floor lands sensibly, not because it changes conclusions.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from kube_foresight.models import ContainerMetrics, ResourceSpec

# Arbitrary anchor — the trace stores time as seconds from start; the absolute
# wall-clock date is irrelevant, only deltas matter.
_EPOCH = datetime(2018, 1, 1, tzinfo=timezone.utc)
_DEFAULT_MACHINE_CORES = 96  # typical Alibaba 2018 host; used only if no join hit


def _load_machine_cores(path: Path) -> dict[str, int]:
    """machine_id → cpu_num (physical cores) from machine_meta.csv."""
    cores: dict[str, int] = {}
    with path.open(newline="") as fh:
        for row in csv.reader(fh):
            if len(row) < 5:
                continue
            machine_id, _ts, _fd1, _fd2, cpu_num = row[0], row[1], row[2], row[3], row[4]
            try:
                cores[machine_id] = int(float(cpu_num))
            except ValueError:
                continue
    return cores


def _load_container_meta(
    path: Path, max_app_groups: int | None
) -> tuple[dict[str, str], dict[str, ResourceSpec], dict[str, float]]:
    """Read container_meta.csv.

    Returns (container_id → app_du, container_id → cpu_spec_cores,
    container_id → mem_request_pct). Limits to the first ``max_app_groups``
    distinct app_du values when set, so a backtest can run on a slice.
    """
    app_of: dict[str, str] = {}
    cpu_spec: dict[str, ResourceSpec] = {}
    mem_request_pct: dict[str, float] = {}
    selected_apps: set[str] = set()

    with path.open(newline="") as fh:
        for row in csv.reader(fh):
            if len(row) < 8:
                continue
            container_id, _machine, _ts, app_du = row[0], row[1], row[2], row[3]
            try:
                cpu_request = float(row[5]) / 100.0  # centi-cores → cores
                cpu_limit = float(row[6]) / 100.0
                mem_size = float(row[7])  # percent of machine memory
            except ValueError:
                continue

            if max_app_groups is not None and app_du not in selected_apps:
                if len(selected_apps) >= max_app_groups:
                    continue
                selected_apps.add(app_du)

            app_of[container_id] = app_du
            cpu_spec[container_id] = ResourceSpec(request=cpu_request, limit=cpu_limit)
            mem_request_pct[container_id] = mem_size

    return app_of, cpu_spec, mem_request_pct


def load_alibaba_trace(
    trace_dir: str | Path,
    *,
    max_app_groups: int | None = 200,
    machine_mem_gib: float = 96.0,
    max_usage_rows: int | None = None,
) -> list[ContainerMetrics]:
    """Build ContainerMetrics from an Alibaba v2018 trace directory.

    Args:
        trace_dir: directory containing machine_meta.csv, container_meta.csv,
            and container_usage.csv.
        max_app_groups: cap on distinct app_du groups to keep (sampling). None = all.
        machine_mem_gib: assumed host memory, used only to express the
            percent-of-machine memory figures as bytes for the model.
        max_usage_rows: stop after this many usage rows (smoke-test guard). None = all.

    Each app_du becomes a deployment; each container becomes a replica.
    """
    trace_dir = Path(trace_dir)
    machine_cores = _load_machine_cores(trace_dir / "machine_meta.csv")
    app_of, cpu_spec, mem_request_pct = _load_container_meta(
        trace_dir / "container_meta.csv", max_app_groups
    )
    mem_bytes_per_pct = machine_mem_gib * (1024**3) / 100.0

    cpu_series: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    mem_series: dict[str, list[tuple[datetime, float]]] = defaultdict(list)

    with (trace_dir / "container_usage.csv").open(newline="") as fh:
        for i, row in enumerate(csv.reader(fh)):
            if max_usage_rows is not None and i >= max_usage_rows:
                break
            if len(row) < 5:
                continue
            container_id, machine_id = row[0], row[1]
            if container_id not in app_of:
                continue  # not in the sampled slice / a batch row
            try:
                ts = _EPOCH + timedelta(seconds=float(row[2]))
                cpu_pct = float(row[3])
                mem_pct = float(row[4])
            except ValueError:
                continue
            cores = machine_cores.get(machine_id, _DEFAULT_MACHINE_CORES)
            cpu_series[container_id].append((ts, cpu_pct / 100.0 * cores))
            mem_series[container_id].append((ts, mem_pct * mem_bytes_per_pct))

    results: list[ContainerMetrics] = []
    for container_id, app_du in app_of.items():
        cpu = sorted(cpu_series.get(container_id, []))
        mem = sorted(mem_series.get(container_id, []))
        if not cpu or not mem:
            continue
        mem_req_bytes = mem_request_pct[container_id] * mem_bytes_per_pct
        results.append(
            ContainerMetrics(
                container_name=app_du,
                pod_name=container_id,
                deployment_name=app_du,
                namespace="alibaba-2018",
                cpu_usage=cpu,
                memory_usage=mem,
                cpu_spec=cpu_spec[container_id],
                memory_spec=ResourceSpec(
                    request=mem_req_bytes, limit=mem_req_bytes * 2
                ),
            )
        )
    return results
