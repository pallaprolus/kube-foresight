"""Abstract base class for metric collectors."""

from __future__ import annotations

from abc import ABC, abstractmethod

from kube_foresight.models import ContainerMetrics


class BaseCollector(ABC):
    """Interface for collecting Kubernetes resource metrics."""

    @abstractmethod
    def collect(
        self,
        namespace: str,
        lookback_hours: int = 168,
        step_seconds: int = 300,
    ) -> list[ContainerMetrics]:
        """Collect CPU and memory metrics for all containers in a namespace."""
        ...

    @abstractmethod
    def check_connection(self) -> tuple[bool, str]:
        """Verify the data source is reachable.

        Returns:
            (is_connected, status_message)
        """
        ...
