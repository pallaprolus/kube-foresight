"""Tests for recommendation strategies."""

import pytest

from kube_foresight.models import ConfidenceLevel, UsageStats
from kube_foresight.recommender.strategies import determine_confidence, recommend_by_percentile


def _make_stats(**kwargs):
    defaults = dict(
        mean=0.1, median=0.09, p95=0.15, p99=0.18, max=0.2,
        min=0.01, std_dev=0.03, sample_count=2016,
    )
    defaults.update(kwargs)
    return UsageStats(**defaults)


def test_recommend_by_percentile_p95():
    stats = _make_stats(p95=0.15)
    req, lim = recommend_by_percentile(stats, current_request=1.0, current_limit=2.0)
    # 0.15 * 1.2 = 0.18
    assert req == 0.18
    assert lim == 0.18 * 1.5  # 0.27


def test_recommend_never_exceeds_current():
    stats = _make_stats(p95=5.0)
    req, lim = recommend_by_percentile(stats, current_request=1.0, current_limit=2.0)
    assert req == 1.0
    assert lim == 2.0


def test_recommend_respects_floor():
    stats = _make_stats(p95=0.001)
    req, lim = recommend_by_percentile(
        stats, current_request=1.0, current_limit=2.0, floor=0.01
    )
    assert req >= 0.01
    assert lim >= 0.01


def test_determine_confidence_high():
    stats = _make_stats(sample_count=2016, std_dev=0.03, mean=0.1)
    assert determine_confidence(stats) == ConfidenceLevel.HIGH


def test_determine_confidence_medium():
    stats = _make_stats(sample_count=1000, std_dev=0.08, mean=0.1)
    assert determine_confidence(stats) == ConfidenceLevel.MEDIUM


def test_determine_confidence_low():
    stats = _make_stats(sample_count=100, std_dev=0.5, mean=0.1)
    assert determine_confidence(stats) == ConfidenceLevel.LOW


def test_invalid_strategy_raises_value_error():
    stats = _make_stats()
    with pytest.raises(ValueError, match="Unknown strategy 'mean'"):
        recommend_by_percentile(stats, current_request=1.0, current_limit=2.0, percentile="mean")
