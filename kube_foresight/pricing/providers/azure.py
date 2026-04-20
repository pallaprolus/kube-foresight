"""Azure AKS pricing provider."""

from __future__ import annotations

from kube_foresight.pricing.providers.base import BasePricingProvider


class AzurePricingProvider(BasePricingProvider):
    """Approximate blended on-demand rates for Azure AKS (East US, D-series v5)."""

    _VCPU_PER_HOUR = 0.04360  # ~$31.83/month per vCPU
    _GIB_PER_HOUR = 0.00478  # ~$3.49/month per GiB

    def cpu_cost_per_hour(self) -> float:
        return self._VCPU_PER_HOUR

    def memory_cost_per_hour_gib(self) -> float:
        return self._GIB_PER_HOUR

    def provider_name(self) -> str:
        return "Azure (East US, on-demand)"
