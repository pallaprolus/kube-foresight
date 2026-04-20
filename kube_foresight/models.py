"""Domain models for kube-foresight."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ResourceType(str, Enum):
    CPU = "cpu"
    MEMORY = "memory"


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SizingCategory(str, Enum):
    UNDER_PROVISIONED = "under-provisioned"
    RIGHT_SIZED = "right-sized"
    OVER_PROVISIONED = "over-provisioned"


class TrendDirection(str, Enum):
    GROWING = "growing"
    DECLINING = "declining"
    STEADY = "steady"
    CYCLIC = "cyclic"


@dataclass
class ResourceSpec:
    """CPU (cores) or Memory (bytes) specification."""

    request: float
    limit: float


@dataclass
class ContainerMetrics:
    """Raw time-series metrics for a single container."""

    container_name: str
    pod_name: str
    deployment_name: str
    namespace: str
    cpu_usage: list[tuple[datetime, float]]  # (timestamp, cores)
    memory_usage: list[tuple[datetime, float]]  # (timestamp, bytes)
    cpu_spec: ResourceSpec
    memory_spec: ResourceSpec


@dataclass
class UsageStats:
    """Computed usage statistics for a resource."""

    mean: float
    median: float
    p95: float
    p99: float
    max: float
    min: float
    std_dev: float
    sample_count: int


@dataclass
class DeploymentProfile:
    """Aggregated profile for a deployment."""

    name: str
    container_name: str
    namespace: str
    replica_count: int
    cpu_stats: UsageStats
    memory_stats: UsageStats
    cpu_spec: ResourceSpec
    memory_spec: ResourceSpec
    cpu_utilization_ratio: float
    memory_utilization_ratio: float
    over_provisioning_score: float
    sizing_category: SizingCategory = SizingCategory.RIGHT_SIZED


@dataclass
class Recommendation:
    """Right-sizing recommendation for a deployment."""

    deployment_name: str
    container_name: str
    namespace: str
    strategy: str
    headroom: float
    current_cpu_request: float
    current_cpu_limit: float
    current_memory_request: float
    current_memory_limit: float
    recommended_cpu_request: float
    recommended_cpu_limit: float
    recommended_memory_request: float
    recommended_memory_limit: float
    cpu_reduction_pct: float
    memory_reduction_pct: float
    confidence: ConfidenceLevel


@dataclass
class CostEstimate:
    """Monthly cost estimate for a deployment."""

    deployment_name: str
    namespace: str
    replica_count: int
    current_monthly_cost_usd: float
    recommended_monthly_cost_usd: float
    monthly_savings_usd: float
    annual_savings_usd: float


@dataclass
class AnalysisReport:
    """Complete analysis output."""

    namespace: str
    total_deployments: int
    analyzed_deployments: int
    profiles: list[DeploymentProfile]
    recommendations: list[Recommendation]
    cost_estimates: list[CostEstimate]
    total_monthly_savings_usd: float
    total_annual_savings_usd: float
    generated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ForecastPoint:
    """A single predicted data point in the future."""

    timestamp: datetime
    value: float
    lower_bound: float
    upper_bound: float


@dataclass
class ResourceForecast:
    """Forecast for a single resource type (CPU or memory)."""

    resource_type: ResourceType
    trend: TrendDirection
    slope_per_day: float
    r_squared: float
    current_value: float
    request_value: float
    limit_value: float
    days_until_request_breach: float | None
    days_until_limit_breach: float | None
    forecast_points: list[ForecastPoint] = field(default_factory=list)
    sufficient_data: bool = True


@dataclass
class DeploymentForecast:
    """Complete forecast for a deployment combining CPU and memory."""

    deployment_name: str
    namespace: str
    cpu_forecast: ResourceForecast
    memory_forecast: ResourceForecast
    risk_level: str  # "critical", "warning", "ok"
    summary: str
