"""Tests for cloud pricing providers and factory."""

import pytest

from kube_foresight.pricing.providers import SUPPORTED_PROVIDERS, get_provider
from kube_foresight.pricing.providers.aws import AWSPricingProvider
from kube_foresight.pricing.providers.azure import AzurePricingProvider
from kube_foresight.pricing.providers.base import BasePricingProvider
from kube_foresight.pricing.providers.gcp import GCPPricingProvider

# --- Individual provider rate tests ---


class TestAWSProvider:
    def test_cpu_rate(self):
        p = AWSPricingProvider()
        assert p.cpu_cost_per_hour() == pytest.approx(0.04048, abs=1e-5)

    def test_memory_rate(self):
        p = AWSPricingProvider()
        assert p.memory_cost_per_hour_gib() == pytest.approx(0.004445, abs=1e-5)

    def test_provider_name(self):
        p = AWSPricingProvider()
        assert "AWS" in p.provider_name()
        assert "us-east-1" in p.provider_name()


class TestGCPProvider:
    def test_cpu_rate(self):
        p = GCPPricingProvider()
        assert p.cpu_cost_per_hour() == pytest.approx(0.03175, abs=1e-5)

    def test_memory_rate(self):
        p = GCPPricingProvider()
        assert p.memory_cost_per_hour_gib() == pytest.approx(0.00425, abs=1e-5)

    def test_provider_name(self):
        p = GCPPricingProvider()
        assert "GCP" in p.provider_name()
        assert "us-central1" in p.provider_name()

    def test_gcp_cheaper_than_aws(self):
        aws = AWSPricingProvider()
        gcp = GCPPricingProvider()
        assert gcp.cpu_cost_per_hour() < aws.cpu_cost_per_hour()
        assert gcp.memory_cost_per_hour_gib() < aws.memory_cost_per_hour_gib()


class TestAzureProvider:
    def test_cpu_rate(self):
        p = AzurePricingProvider()
        assert p.cpu_cost_per_hour() == pytest.approx(0.04360, abs=1e-5)

    def test_memory_rate(self):
        p = AzurePricingProvider()
        assert p.memory_cost_per_hour_gib() == pytest.approx(0.00478, abs=1e-5)

    def test_provider_name(self):
        p = AzurePricingProvider()
        assert "Azure" in p.provider_name()
        assert "East US" in p.provider_name()

    def test_azure_most_expensive(self):
        aws = AWSPricingProvider()
        gcp = GCPPricingProvider()
        azure = AzurePricingProvider()
        assert azure.cpu_cost_per_hour() > aws.cpu_cost_per_hour()
        assert azure.cpu_cost_per_hour() > gcp.cpu_cost_per_hour()


# --- Factory tests ---


class TestGetProvider:
    def test_aws(self):
        p = get_provider("aws")
        assert isinstance(p, AWSPricingProvider)

    def test_gcp(self):
        p = get_provider("gcp")
        assert isinstance(p, GCPPricingProvider)

    def test_azure(self):
        p = get_provider("azure")
        assert isinstance(p, AzurePricingProvider)

    def test_case_insensitive(self):
        assert isinstance(get_provider("AWS"), AWSPricingProvider)
        assert isinstance(get_provider("Gcp"), GCPPricingProvider)
        assert isinstance(get_provider("AZURE"), AzurePricingProvider)

    def test_strips_whitespace(self):
        assert isinstance(get_provider("  aws  "), AWSPricingProvider)

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown cloud provider"):
            get_provider("digitalocean")

    def test_supported_providers_sorted(self):
        assert SUPPORTED_PROVIDERS == ["aws", "azure", "gcp"]

    def test_all_providers_implement_interface(self):
        for name in SUPPORTED_PROVIDERS:
            p = get_provider(name)
            assert isinstance(p, BasePricingProvider)
            assert isinstance(p.cpu_cost_per_hour(), float)
            assert isinstance(p.memory_cost_per_hour_gib(), float)
            assert isinstance(p.provider_name(), str)
            assert p.cpu_cost_per_hour() > 0
            assert p.memory_cost_per_hour_gib() > 0

    def test_each_provider_has_unique_name(self):
        names = {get_provider(n).provider_name() for n in SUPPORTED_PROVIDERS}
        assert len(names) == len(SUPPORTED_PROVIDERS)
