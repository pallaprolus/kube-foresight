"""AWS EKS pricing provider."""

from __future__ import annotations

from kube_foresight.pricing.providers.base import BasePricingProvider


class AWSPricingProvider(BasePricingProvider):
    """Approximate blended on-demand rates for AWS EKS (us-east-1, m5/m6i family)."""

    _VCPU_PER_HOUR = 0.04048  # ~$29.15/month per vCPU
    _GIB_PER_HOUR = 0.004445  # ~$3.20/month per GiB

    def cpu_cost_per_hour(self) -> float:
        return self._VCPU_PER_HOUR

    def memory_cost_per_hour_gib(self) -> float:
        return self._GIB_PER_HOUR

    def provider_name(self) -> str:
        return "AWS (us-east-1, on-demand)"
