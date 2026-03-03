"""Shared test fixtures."""

import pytest

from kube_foresight.collector.mock import MockCollector


@pytest.fixture
def mock_collector():
    return MockCollector(seed=42)


@pytest.fixture
def mock_metrics(mock_collector):
    return mock_collector.collect(namespace="test-ns")
