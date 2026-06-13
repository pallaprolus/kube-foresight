"""Generate tiny synthetic fixtures in Alibaba v2018 CSV format.

Deterministic (fixed seed). Produces three app_du groups with distinct shapes
so the backtest exercises the savings-vs-violation trade-off. Shapes assume the
default train_fraction of 0.7 (the level shift lands at 70% of the window):

  web-steady  : low steady usage on a 4-core request → big safe savings on every strategy
  api-bursty  : 0.6-core baseline + rare 4-8x spikes  → p95 under-sizes (violations);
                p99/max cap at current (safe, less savings)
  worker-drift: flat in train, then ramps up in test  → train-based rec looks safe, but the
                held-out future breaches it (concept drift)

Run: ``python -m benchmarks.fixtures._generate``
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
MACHINE_CORES = 96
N_POINTS = 240
STEP = 500  # seconds → ~33h span
_SHIFT = int(N_POINTS * 0.7)  # where worker-drift steps up (matches default split)
RNG = np.random.default_rng(7)

# app_du: (cpu_cores [request == limit], mem_alloc_pct, n_replicas, shape)
APPS = {
    "web-steady": (4.0, 20.0, 2, "steady"),
    "api-bursty": (4.0, 25.0, 2, "bursty"),
    "worker-drift": (4.0, 15.0, 1, "drift"),
}


def _cpu_util_series(shape: str, limit_cores: float) -> np.ndarray:
    """CPU usage as percent of the container's own limit (matches the trace)."""
    if shape == "steady":
        cores = np.full(N_POINTS, 0.8)
    elif shape == "bursty":
        cores = np.full(N_POINTS, 0.6)
        mask = RNG.random(N_POINTS) < 0.02  # rare → above p95, caught by p99/max
        cores[mask] = RNG.uniform(3.5, 8.0, mask.sum())  # clipped to limit below
    elif shape == "drift":
        cores = np.full(N_POINTS, 0.5)
        cores[_SHIFT:] = np.linspace(0.5, 6.0, N_POINTS - _SHIFT)  # unseen in train
    else:
        cores = np.full(N_POINTS, 0.8)
    cores = np.maximum(cores + RNG.normal(0, 0.05, N_POINTS), 0.0)
    return np.clip(cores / limit_cores * 100.0, 0.0, 100.0)


def _mem_util_series(shape: str) -> np.ndarray:
    """Memory usage as percent of the container's own allocation (~13%, safe)."""
    base = np.full(N_POINTS, 13.0)
    return np.clip(base + RNG.normal(0, 1.0, N_POINTS), 0.0, 100.0)


def main() -> None:
    machine_id = "m1"
    with (HERE / "machine_meta.csv").open("w", newline="") as fh:
        # machine_id, time_stamp, fd1, fd2, cpu_num, mem_size, status (unused by adapter)
        csv.writer(fh).writerow([machine_id, 0, "1", "2", MACHINE_CORES, 100.0, "USING"])

    meta_rows = []
    usage_rows = []
    cid = 0
    for app, (cpu_cores, mem_alloc_pct, replicas, shape) in APPS.items():
        for _ in range(replicas):
            cid += 1
            container_id = f"c{cid}"
            # container_id, machine_id, ts, app_du, status, cpu_request, cpu_limit, mem_size
            meta_rows.append(
                [container_id, machine_id, 0, app, "started",
                 int(cpu_cores * 100), int(cpu_cores * 100), mem_alloc_pct]
            )
            cpu_util = _cpu_util_series(shape, cpu_cores)
            mem_util = _mem_util_series(shape)
            for i in range(N_POINTS):
                usage_rows.append(
                    [container_id, machine_id, i * STEP,
                     round(cpu_util[i], 4), round(mem_util[i], 4)]
                )

    with (HERE / "container_meta.csv").open("w", newline="") as fh:
        csv.writer(fh).writerows(meta_rows)
    with (HERE / "container_usage.csv").open("w", newline="") as fh:
        csv.writer(fh).writerows(usage_rows)

    print(f"Wrote {len(meta_rows)} containers, {len(usage_rows)} usage rows to {HERE}")


if __name__ == "__main__":
    main()
