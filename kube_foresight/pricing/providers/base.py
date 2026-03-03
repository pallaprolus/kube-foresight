"""Abstract base class for cloud pricing providers."""

from __future__ import annotations

from abc import ABC, abstractmethod


class BasePricingProvider(ABC):
    """Interface for cloud pricing."""

    @abstractmethod
    def cpu_cost_per_hour(self) -> float:
        """Cost per vCPU-hour in USD."""
        ...

    @abstractmethod
    def memory_cost_per_hour_gib(self) -> float:
        """Cost per GiB-hour in USD."""
        ...

    @abstractmethod
    def provider_name(self) -> str:
        ...
