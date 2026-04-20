"""GCP GKE pricing provider."""

from __future__ import annotations

from kube_foresight.pricing.providers.base import BasePricingProvider


class GCPPricingProvider(BasePricingProvider):
    """Approximate blended on-demand rates for GCP GKE (us-central1, e2-standard family)."""

    _VCPU_PER_HOUR = 0.03175  # ~$23.18/month per vCPU
    _GIB_PER_HOUR = 0.00425  # ~$3.10/month per GiB

    def cpu_cost_per_hour(self) -> float:
        return self._VCPU_PER_HOUR

    def memory_cost_per_hour_gib(self) -> float:
        return self._GIB_PER_HOUR

    def provider_name(self) -> str:
        return "GCP (us-central1, on-demand)"
