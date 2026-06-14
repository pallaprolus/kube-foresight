"""Usage statistics computation."""

from __future__ import annotations

from collections import defaultdict

import numpy as np

from kube_foresight.models import ContainerMetrics, UsageStats


def compute_usage_stats(values: list[float]) -> UsageStats:
    """Compute descriptive statistics for a usage time-series.

    Statistics are computed over the **raw** samples — usage spikes are
    deliberately *not* filtered out. For right-sizing, the upper tail is
    signal, not noise: a request set below a real demand spike causes CPU
    throttling or OOM kills, so under-provisioning is the dangerous error.
    The percentile strategies (p95/p99) are themselves tail-robust, and
    computing ``std_dev``/``mean`` on raw data keeps the coefficient-of-variation
    confidence signal representative of the true variability rather than
    artificially low.

    Filtering of genuinely spurious readings (e.g. impossible values from a
    metrics-collection glitch) belongs at the collector layer, not here.
    """
    arr = np.array(values)
    return UsageStats(
        mean=float(np.mean(arr)),
        median=float(np.median(arr)),
        p95=float(np.percentile(arr, 95)),
        p99=float(np.percentile(arr, 99)),
        max=float(np.max(arr)),
        min=float(np.min(arr)),
        std_dev=float(np.std(arr)),
        sample_count=len(arr),
    )


def aggregate_deployment_metrics(
    container_metrics: list[ContainerMetrics],
) -> dict[str, list[ContainerMetrics]]:
    """Group container metrics by deployment name."""
    grouped: dict[str, list[ContainerMetrics]] = defaultdict(list)
    for cm in container_metrics:
        grouped[cm.deployment_name].append(cm)
    return dict(grouped)
