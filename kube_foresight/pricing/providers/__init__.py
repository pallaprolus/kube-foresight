"""Cloud pricing providers."""

from __future__ import annotations

from kube_foresight.pricing.providers.aws import AWSPricingProvider
from kube_foresight.pricing.providers.azure import AzurePricingProvider
from kube_foresight.pricing.providers.base import BasePricingProvider
from kube_foresight.pricing.providers.gcp import GCPPricingProvider

_PROVIDERS: dict[str, type[BasePricingProvider]] = {
    "aws": AWSPricingProvider,
    "gcp": GCPPricingProvider,
    "azure": AzurePricingProvider,
}

SUPPORTED_PROVIDERS = sorted(_PROVIDERS.keys())


def get_provider(name: str = "aws") -> BasePricingProvider:
    """Get a pricing provider by name.

    Args:
        name: Provider identifier (case-insensitive). One of: aws, gcp, azure.

    Returns:
        An instance of the requested pricing provider.

    Raises:
        ValueError: If the provider name is not recognized.
    """
    key = name.strip().lower()
    cls = _PROVIDERS.get(key)
    if cls is None:
        raise ValueError(
            f"Unknown cloud provider '{name}'. "
            f"Supported: {', '.join(SUPPORTED_PROVIDERS)}"
        )
    return cls()
