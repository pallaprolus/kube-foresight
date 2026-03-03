"""Usage statistics computation."""

from __future__ import annotations

from collections import defaultdict

import numpy as np

from kube_foresight.models import ContainerMetrics, UsageStats


def filter_anomalies(values: list[float], iqr_multiplier: float = 1.5) -> list[float]:
    """Remove outliers using the IQR method.

    Points beyond Q1 - k*IQR or Q3 + k*IQR are removed.  Returns the
    original list unchanged when fewer than 4 data points exist (too few
    for meaningful quartile computation) or when all values are identical
    (IQR == 0).
    """
    if len(values) < 4:
        return values
    arr = np.array(values)
    q1 = float(np.percentile(arr, 25))
    q3 = float(np.percentile(arr, 75))
    iqr = q3 - q1
    if iqr == 0:
        return values
    lower = q1 - iqr_multiplier * iqr
    upper = q3 + iqr_multiplier * iqr
    filtered = arr[(arr >= lower) & (arr <= upper)]
    return filtered.tolist()


def compute_usage_stats(values: list[float]) -> UsageStats:
    """Compute descriptive statistics for a usage time-series.

    Anomalous data points are filtered out via IQR before computing stats
    so that occasional spikes do not inflate percentile-based recommendations.
    """
    cleaned = filter_anomalies(values)
    arr = np.array(cleaned)
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
