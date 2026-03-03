"""Cost estimation for resource right-sizing."""

from __future__ import annotations

from kube_foresight.models import CostEstimate, DeploymentProfile, Recommendation
from kube_foresight.pricing.providers.aws import AWSPricingProvider
from kube_foresight.pricing.providers.base import BasePricingProvider

HOURS_PER_MONTH = 730  # 365.25 * 24 / 12


def estimate_cost(
    profile: DeploymentProfile,
    recommendation: Recommendation,
    provider: BasePricingProvider | None = None,
) -> CostEstimate:
    """Estimate monthly cost savings for a single deployment.

    Cost is based on resource requests (what is reserved), not actual usage.
    """
    if provider is None:
        provider = AWSPricingProvider()

    replicas = profile.replica_count
    mem_gib_current = profile.memory_spec.request / (1024**3)
    mem_gib_recommended = recommendation.recommended_memory_request / (1024**3)

    current_cost = (
        profile.cpu_spec.request * provider.cpu_cost_per_hour()
        + mem_gib_current * provider.memory_cost_per_hour_gib()
    ) * HOURS_PER_MONTH * replicas

    recommended_cost = (
        recommendation.recommended_cpu_request * provider.cpu_cost_per_hour()
        + mem_gib_recommended * provider.memory_cost_per_hour_gib()
    ) * HOURS_PER_MONTH * replicas

    savings = current_cost - recommended_cost
    return CostEstimate(
        deployment_name=profile.name,
        namespace=profile.namespace,
        replica_count=replicas,
        current_monthly_cost_usd=round(current_cost, 2),
        recommended_monthly_cost_usd=round(recommended_cost, 2),
        monthly_savings_usd=round(savings, 2),
        annual_savings_usd=round(savings * 12, 2),
    )


def estimate_namespace_costs(
    profiles: list[DeploymentProfile],
    recommendations: list[Recommendation],
    provider: BasePricingProvider | None = None,
) -> list[CostEstimate]:
    """Estimate costs for all deployments with matching recommendations."""
    rec_map = {r.deployment_name: r for r in recommendations}
    estimates: list[CostEstimate] = []
    for profile in profiles:
        rec = rec_map.get(profile.name)
        if rec:
            estimates.append(estimate_cost(profile, rec, provider))
    return estimates
