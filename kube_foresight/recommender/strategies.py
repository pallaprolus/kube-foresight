"""Right-sizing strategies and confidence determination."""

from __future__ import annotations

from kube_foresight.models import ConfidenceLevel, UsageStats


def recommend_by_percentile(
    stats: UsageStats,
    current_request: float,
    current_limit: float,
    percentile: str = "p95",
    headroom: float = 0.20,
    limit_ratio: float = 1.5,
    floor: float = 0.0,
    direction: str = "down",
) -> tuple[float, float]:
    """Compute recommended request and limit based on usage percentile.

    Args:
        direction: "down" to only decrease (over-provisioned),
                   "up" to only increase (under-provisioned).

    Returns:
        (recommended_request, recommended_limit)
    """
    base_values = {
        "p95": stats.p95,
        "p99": stats.p99,
        "max": stats.max,
    }
    if percentile not in base_values:
        raise ValueError(
            f"Unknown strategy '{percentile}'. Valid options: {', '.join(sorted(base_values))}"
        )
    base = base_values[percentile]
    recommended_request = base * (1 + headroom)
    recommended_limit = recommended_request * limit_ratio

    if direction == "down":
        # Only right-size down, never up
        recommended_request = min(recommended_request, current_request)
        recommended_limit = min(recommended_limit, current_limit)
    else:
        # Only right-size up, never down
        recommended_request = max(recommended_request, current_request)
        recommended_limit = max(recommended_limit, current_limit)

    # Apply floor
    recommended_request = max(recommended_request, floor)
    recommended_limit = max(recommended_limit, floor)

    return recommended_request, recommended_limit


def determine_confidence(stats: UsageStats) -> ConfidenceLevel:
    """Determine confidence level based on data quality.

    High: >= 2016 samples (7 days @ 5min), CV < 0.5
    Medium: >= 864 samples (3 days @ 5min), CV < 1.0
    Low: everything else
    """
    cv = stats.std_dev / stats.mean if stats.mean > 0 else float("inf")
    if stats.sample_count >= 2016 and cv < 0.5:
        return ConfidenceLevel.HIGH
    if stats.sample_count >= 864 and cv < 1.0:
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW
