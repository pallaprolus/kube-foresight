"""Service layer: wraps the analysis pipeline with in-memory caching."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum

import yaml

from kube_foresight.analyzer.profiler import profile_deployments, rank_by_over_provisioning
from kube_foresight.collector import get_collector
from kube_foresight.models import (
    AnalysisReport,
    ContainerMetrics,
    CostEstimate,
    DeploymentProfile,
    Recommendation,
)
from kube_foresight.pricing.estimator import estimate_namespace_costs
from kube_foresight.recommender.engine import generate_recommendations
from kube_foresight.recommender.patch import generate_patch


class AnalysisStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


@dataclass
class DeploymentDetail:
    """Everything needed to render a single deployment detail page."""

    profile: DeploymentProfile
    recommendation: Recommendation | None
    cost_estimate: CostEstimate | None
    raw_metrics: list[ContainerMetrics]
    patch_yaml: str | None


@dataclass
class AnalysisCache:
    """In-memory cache for a single analysis run."""

    report: AnalysisReport | None = None
    raw_metrics: list[ContainerMetrics] = field(default_factory=list)
    all_profiles: list[DeploymentProfile] = field(default_factory=list)
    ranked_profiles: list[DeploymentProfile] = field(default_factory=list)
    recommendations: list[Recommendation] = field(default_factory=list)
    cost_estimates: list[CostEstimate] = field(default_factory=list)
    profile_map: dict[str, DeploymentProfile] = field(default_factory=dict)
    recommendation_map: dict[str, Recommendation] = field(default_factory=dict)
    cost_map: dict[str, CostEstimate] = field(default_factory=dict)
    metrics_by_deployment: dict[str, list[ContainerMetrics]] = field(default_factory=dict)


class AnalysisService:
    """Wraps the kube-foresight pipeline with caching."""

    def __init__(self) -> None:
        self._status = AnalysisStatus.IDLE
        self._cache = AnalysisCache()
        self._error: str | None = None

    @property
    def status(self) -> AnalysisStatus:
        return self._status

    @property
    def has_results(self) -> bool:
        return self._cache.report is not None

    @property
    def error(self) -> str | None:
        return self._error

    def test_connection(
        self, mode: str, prometheus_url: str | None = None, seed: int = 42, **kwargs
    ) -> tuple[bool, str]:
        try:
            collector = get_collector(mode=mode, prometheus_url=prometheus_url, seed=seed, **kwargs)
            return collector.check_connection()
        except Exception as e:
            return False, str(e)

    def run_analysis(
        self,
        mode: str = "mock",
        prometheus_url: str | None = None,
        namespace: str = "default",
        lookback_hours: int = 168,
        strategy: str = "p95",
        headroom: float = 0.20,
        top_n: int = 10,
        seed: int = 42,
        **kwargs,
    ) -> AnalysisReport:
        self._status = AnalysisStatus.RUNNING
        self._error = None

        try:
            collector = get_collector(mode=mode, prometheus_url=prometheus_url, seed=seed, **kwargs)
            raw_metrics = collector.collect(namespace=namespace, lookback_hours=lookback_hours)

            all_profiles = profile_deployments(raw_metrics)
            ranked = rank_by_over_provisioning(all_profiles, top_n=top_n)

            recommendations = generate_recommendations(
                ranked, strategy=strategy, headroom=headroom
            )
            cost_estimates = estimate_namespace_costs(ranked, recommendations)

            total_monthly = sum(e.monthly_savings_usd for e in cost_estimates)
            total_annual = sum(e.annual_savings_usd for e in cost_estimates)

            report = AnalysisReport(
                namespace=namespace,
                total_deployments=len(all_profiles),
                analyzed_deployments=len(ranked),
                profiles=ranked,
                recommendations=recommendations,
                cost_estimates=cost_estimates,
                total_monthly_savings_usd=round(total_monthly, 2),
                total_annual_savings_usd=round(total_annual, 2),
            )

            grouped: dict[str, list[ContainerMetrics]] = defaultdict(list)
            for m in raw_metrics:
                grouped[m.deployment_name].append(m)

            self._cache = AnalysisCache(
                report=report,
                raw_metrics=raw_metrics,
                all_profiles=all_profiles,
                ranked_profiles=ranked,
                recommendations=recommendations,
                cost_estimates=cost_estimates,
                profile_map={p.name: p for p in ranked},
                recommendation_map={r.deployment_name: r for r in recommendations},
                cost_map={c.deployment_name: c for c in cost_estimates},
                metrics_by_deployment=dict(grouped),
            )

            self._status = AnalysisStatus.DONE
            return report

        except Exception as e:
            self._status = AnalysisStatus.ERROR
            self._error = str(e)
            raise

    def get_report(self) -> AnalysisReport | None:
        return self._cache.report

    def get_deployment_detail(self, name: str) -> DeploymentDetail | None:
        profile = self._cache.profile_map.get(name)
        if not profile:
            return None
        rec = self._cache.recommendation_map.get(name)
        cost = self._cache.cost_map.get(name)
        metrics = self._cache.metrics_by_deployment.get(name, [])
        patch_yaml = None
        if rec:
            patch_yaml = yaml.dump(generate_patch(rec), default_flow_style=False, sort_keys=False)
        return DeploymentDetail(
            profile=profile,
            recommendation=rec,
            cost_estimate=cost,
            raw_metrics=metrics,
            patch_yaml=patch_yaml,
        )

    def get_timeseries_data(self, deployment_name: str) -> dict:
        """Extract time-series data formatted for Chart.js."""
        metrics = self._cache.metrics_by_deployment.get(deployment_name, [])
        if not metrics:
            return {}
        m = metrics[0]
        # Downsample for chart performance: take every 6th point (~30min intervals)
        step = max(1, len(m.cpu_usage) // 336)
        return {
            "labels": [ts.isoformat() for ts, _ in m.cpu_usage[::step]],
            "cpu": {
                "usage": [round(v, 4) for _, v in m.cpu_usage[::step]],
                "request": m.cpu_spec.request,
                "limit": m.cpu_spec.limit,
            },
            "memory": {
                "usage": [round(v / (1024**2), 1) for _, v in m.memory_usage[::step]],
                "request": round(m.memory_spec.request / (1024**2), 1),
                "limit": round(m.memory_spec.limit / (1024**2), 1),
            },
        }

    def get_all_patches(self) -> list[dict[str, str]]:
        patches = []
        for rec in self._cache.recommendations:
            patch_dict = generate_patch(rec)
            patches.append(
                {
                    "name": rec.deployment_name,
                    "yaml": yaml.dump(patch_dict, default_flow_style=False, sort_keys=False),
                }
            )
        return patches
