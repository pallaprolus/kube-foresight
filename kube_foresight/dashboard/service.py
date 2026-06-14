"""Service layer: wraps the analysis pipeline with in-memory caching."""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum

import yaml

from kube_foresight.analyzer.profiler import profile_deployments, rank_by_over_provisioning
from kube_foresight.audit import AuditLog
from kube_foresight.collector import get_collector
from kube_foresight.hpa import HPAConflict, HPAInfo, check_hpa_conflicts, detect_hpas
from kube_foresight.models import (
    AnalysisReport,
    ContainerMetrics,
    CostEstimate,
    DeploymentForecast,
    DeploymentProfile,
    Recommendation,
)
from kube_foresight.pricing.estimator import estimate_namespace_costs
from kube_foresight.pricing.providers import get_provider
from kube_foresight.recommender.engine import generate_recommendations
from kube_foresight.recommender.patch import generate_patch

logger = logging.getLogger("kube_foresight.dashboard.service")


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
    hpa_conflicts: list[HPAConflict] = field(default_factory=list)


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
    hpas: list[HPAInfo] = field(default_factory=list)
    hpa_map: dict[str, list[HPAInfo]] = field(default_factory=dict)


class AnalysisService:
    """Wraps the kube-foresight pipeline with caching."""

    def __init__(self, audit_db_path: str | None = None) -> None:
        self._status = AnalysisStatus.IDLE
        self._cache = AnalysisCache()
        self._error: str | None = None
        self._audit = AuditLog(db_path=audit_db_path)
        self._analyzed_namespaces: list[str] = []
        self._last_params: dict = {}

    @property
    def status(self) -> AnalysisStatus:
        return self._status

    @property
    def has_results(self) -> bool:
        return self._cache.report is not None

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def audit_log(self) -> AuditLog:
        return self._audit

    @property
    def analyzed_namespaces(self) -> list[str]:
        return list(self._analyzed_namespaces)

    @property
    def provider_name(self) -> str:
        return get_provider(os.environ.get("KF_CLOUD_PROVIDER", "aws")).provider_name()

    @property
    def last_analysis_params(self) -> dict:
        return dict(self._last_params)

    def get_available_namespaces(
        self, mode: str, prometheus_url: str | None = None, seed: int = 42, **kwargs,
    ) -> list[str]:
        """Return namespace names available from the data source."""
        try:
            collector = get_collector(
                mode=mode, prometheus_url=prometheus_url, seed=seed, **kwargs,
            )
            return collector.list_namespaces()
        except Exception:
            logger.debug("Failed to list namespaces", exc_info=True)
            return []

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
        strategy: str = "p99",
        headroom: float = 0.20,
        top_n: int = 10,
        seed: int = 42,
        **kwargs,
    ) -> AnalysisReport:
        self._status = AnalysisStatus.RUNNING
        self._error = None
        self._last_params = {
            "mode": mode, "prometheus_url": prometheus_url,
            "namespace": namespace, "lookback_hours": lookback_hours,
            "strategy": strategy, "headroom": headroom,
            "top_n": top_n, "seed": seed, **kwargs,
        }

        try:
            collector = get_collector(mode=mode, prometheus_url=prometheus_url, seed=seed, **kwargs)
            raw_metrics = collector.collect(namespace=namespace, lookback_hours=lookback_hours)

            all_profiles = profile_deployments(raw_metrics)
            ranked = rank_by_over_provisioning(all_profiles, top_n=top_n)

            # Generate recommendations for all profiles (engine skips right-sized)
            recommendations = generate_recommendations(
                all_profiles, strategy=strategy, headroom=headroom
            )
            provider = get_provider(os.environ.get("KF_CLOUD_PROVIDER", "aws"))
            cost_estimates = estimate_namespace_costs(
                all_profiles, recommendations, provider=provider,
            )

            total_monthly = sum(e.monthly_savings_usd for e in cost_estimates)
            total_annual = sum(e.annual_savings_usd for e in cost_estimates)

            report = AnalysisReport(
                namespace=namespace,
                total_deployments=len(all_profiles),
                analyzed_deployments=len(all_profiles),
                profiles=all_profiles,
                recommendations=recommendations,
                cost_estimates=cost_estimates,
                total_monthly_savings_usd=round(total_monthly, 2),
                total_annual_savings_usd=round(total_annual, 2),
            )

            grouped: dict[str, list[ContainerMetrics]] = defaultdict(list)
            for m in raw_metrics:
                grouped[m.deployment_name].append(m)

            # Detect HPAs (best-effort, only for k8s mode)
            hpas: list[HPAInfo] = []
            if mode in ("k8s", "prometheus"):
                hpas = detect_hpas(namespace)

            hpa_map: dict[str, list[HPAInfo]] = defaultdict(list)
            for h in hpas:
                hpa_map[h.deployment_name].append(h)

            self._cache = AnalysisCache(
                report=report,
                raw_metrics=raw_metrics,
                all_profiles=all_profiles,
                ranked_profiles=ranked,
                recommendations=recommendations,
                cost_estimates=cost_estimates,
                profile_map={p.name: p for p in all_profiles},
                recommendation_map={r.deployment_name: r for r in recommendations},
                cost_map={c.deployment_name: c for c in cost_estimates},
                metrics_by_deployment=dict(grouped),
                hpas=hpas,
                hpa_map=dict(hpa_map),
            )

            if namespace not in self._analyzed_namespaces:
                self._analyzed_namespaces.append(namespace)

            self._status = AnalysisStatus.DONE
            logger.info(
                "Analysis complete: %d deployments, %d recommendations, %d HPAs in '%s'",
                len(all_profiles), len(recommendations), len(hpas), namespace,
            )
            return report

        except Exception as e:
            self._status = AnalysisStatus.ERROR
            self._error = str(e)
            raise

    def run_multi_namespace_analysis(
        self,
        namespaces: list[str],
        mode: str = "mock",
        prometheus_url: str | None = None,
        lookback_hours: int = 168,
        strategy: str = "p99",
        headroom: float = 0.20,
        top_n: int = 10,
        seed: int = 42,
        **kwargs,
    ) -> AnalysisReport:
        """Run analysis across multiple namespaces and merge results."""
        self._status = AnalysisStatus.RUNNING
        self._error = None
        self._last_params = {
            "namespaces": namespaces, "mode": mode,
            "prometheus_url": prometheus_url, "lookback_hours": lookback_hours,
            "strategy": strategy, "headroom": headroom,
            "top_n": top_n, "seed": seed, **kwargs,
        }

        try:
            all_raw_metrics: list[ContainerMetrics] = []
            all_profiles: list[DeploymentProfile] = []
            all_hpas: list[HPAInfo] = []

            for ns in namespaces:
                collector = get_collector(
                    mode=mode, prometheus_url=prometheus_url,
                    seed=seed, **kwargs,
                )
                raw_metrics = collector.collect(namespace=ns, lookback_hours=lookback_hours)
                all_raw_metrics.extend(raw_metrics)

                profiles = profile_deployments(raw_metrics)
                all_profiles.extend(profiles)

                if mode in ("k8s", "prometheus"):
                    all_hpas.extend(detect_hpas(ns))

            ranked = rank_by_over_provisioning(all_profiles, top_n=top_n)
            recommendations = generate_recommendations(
                all_profiles, strategy=strategy, headroom=headroom
            )
            provider = get_provider(os.environ.get("KF_CLOUD_PROVIDER", "aws"))
            cost_estimates = estimate_namespace_costs(
                all_profiles, recommendations, provider=provider,
            )

            total_monthly = sum(e.monthly_savings_usd for e in cost_estimates)
            total_annual = sum(e.annual_savings_usd for e in cost_estimates)

            ns_label = ", ".join(namespaces)
            report = AnalysisReport(
                namespace=ns_label,
                total_deployments=len(all_profiles),
                analyzed_deployments=len(all_profiles),
                profiles=all_profiles,
                recommendations=recommendations,
                cost_estimates=cost_estimates,
                total_monthly_savings_usd=round(total_monthly, 2),
                total_annual_savings_usd=round(total_annual, 2),
            )

            grouped: dict[str, list[ContainerMetrics]] = defaultdict(list)
            for m in all_raw_metrics:
                grouped[m.deployment_name].append(m)

            hpa_map: dict[str, list[HPAInfo]] = defaultdict(list)
            for h in all_hpas:
                hpa_map[h.deployment_name].append(h)

            self._cache = AnalysisCache(
                report=report,
                raw_metrics=all_raw_metrics,
                all_profiles=all_profiles,
                ranked_profiles=ranked,
                recommendations=recommendations,
                cost_estimates=cost_estimates,
                profile_map={p.name: p for p in all_profiles},
                recommendation_map={r.deployment_name: r for r in recommendations},
                cost_map={c.deployment_name: c for c in cost_estimates},
                metrics_by_deployment=dict(grouped),
                hpas=all_hpas,
                hpa_map=dict(hpa_map),
            )

            self._analyzed_namespaces = list(namespaces)
            self._status = AnalysisStatus.DONE
            logger.info(
                "Multi-namespace analysis complete: %d namespaces, %d deployments",
                len(namespaces), len(all_profiles),
            )
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
        hpa_conflicts: list[HPAConflict] = []
        if rec:
            patch_yaml = yaml.dump(generate_patch(rec), default_flow_style=False, sort_keys=False)
            hpa_conflicts = check_hpa_conflicts(
                deployment_name=name,
                namespace=rec.namespace,
                hpas=self._cache.hpas,
                recommended_cpu_request=rec.recommended_cpu_request,
                current_cpu_request=rec.current_cpu_request,
            )
        return DeploymentDetail(
            profile=profile,
            recommendation=rec,
            cost_estimate=cost,
            raw_metrics=metrics,
            patch_yaml=patch_yaml,
            hpa_conflicts=hpa_conflicts,
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

    def get_forecast(
        self, deployment_name: str, forecast_days: int = 30,
    ) -> DeploymentForecast | None:
        """Generate a forecast for a specific deployment."""
        from kube_foresight.forecaster import generate_forecast

        metrics = self._cache.metrics_by_deployment.get(deployment_name, [])
        if not metrics:
            return None
        return generate_forecast(metrics[0], forecast_days=forecast_days)

    def get_all_forecasts(self, forecast_days: int = 30) -> list[DeploymentForecast]:
        """Generate forecasts for all analyzed deployments."""
        from kube_foresight.forecaster import generate_forecast

        forecasts: list[DeploymentForecast] = []
        for name, metrics_list in self._cache.metrics_by_deployment.items():
            if metrics_list:
                forecasts.append(generate_forecast(metrics_list[0], forecast_days=forecast_days))
        return forecasts

    def get_at_risk_deployments(self) -> list[DeploymentForecast]:
        """Return forecasts with risk_level != 'ok', sorted by severity."""
        risk_order = {"critical": 0, "warning": 1, "ok": 2}
        all_fc = self.get_all_forecasts()
        at_risk = [fc for fc in all_fc if fc.risk_level != "ok"]
        return sorted(at_risk, key=lambda f: risk_order.get(f.risk_level, 3))

    def get_hpa_conflicts(self, deployment_name: str) -> list[HPAConflict]:
        """Get HPA conflicts for a specific deployment."""
        rec = self._cache.recommendation_map.get(deployment_name)
        if not rec:
            return []
        return check_hpa_conflicts(
            deployment_name=deployment_name,
            namespace=rec.namespace,
            hpas=self._cache.hpas,
            recommended_cpu_request=rec.recommended_cpu_request,
            current_cpu_request=rec.current_cpu_request,
        )

    def apply_patch(
        self,
        deployment_name: str,
        dry_run: bool = False,
        source_ip: str = "",
    ) -> tuple[bool, str]:
        """Apply a patch for a specific deployment via the Kubernetes Python client."""
        rec = self._cache.recommendation_map.get(deployment_name)
        if not rec:
            return False, f"No recommendation found for '{deployment_name}'"

        patch_dict = generate_patch(rec)
        namespace = patch_dict["metadata"]["namespace"]
        body = {"spec": patch_dict["spec"]}
        patch_yaml = yaml.dump(patch_dict, default_flow_style=False, sort_keys=False)

        try:
            from kubernetes import client, config

            try:
                config.load_incluster_config()
            except config.ConfigException:
                config.load_kube_config()

            apps_v1 = client.AppsV1Api()
            dry_run_param = "All" if dry_run else None

            apps_v1.patch_namespaced_deployment(
                name=deployment_name,
                namespace=namespace,
                body=body,
                dry_run=dry_run_param,
            )

            action = "dry-run" if dry_run else "apply"
            action_label = "Dry-run" if dry_run else "Applied"
            msg = (
                f"{action_label} patch for"
                f" deployment/{deployment_name} in {namespace}"
            )
            logger.info(msg, extra={"deployment": deployment_name, "namespace": namespace})

            # Record in audit log
            self._audit.record(
                action=action,
                deployment_name=deployment_name,
                namespace=namespace,
                dry_run=dry_run,
                success=True,
                message=msg,
                source_ip=source_ip,
                patch_yaml=patch_yaml,
            )

            return True, msg

        except ImportError:
            return False, (
                "kubernetes package not installed. "
                "Install with: pip install 'kube-foresight[k8s]'"
            )
        except Exception as e:
            err_msg = str(e)
            if hasattr(e, "reason"):
                err_msg = e.reason
            elif hasattr(e, "body"):
                err_msg = str(e.body)[:200]
            logger.error("Patch failed for %s: %s", deployment_name, err_msg)

            self._audit.record(
                action="dry-run" if dry_run else "apply",
                deployment_name=deployment_name,
                namespace=namespace,
                dry_run=dry_run,
                success=False,
                message=err_msg,
                source_ip=source_ip,
                patch_yaml=patch_yaml,
            )

            return False, err_msg

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

    def get_multi_cloud_costs(self) -> dict[str, list[CostEstimate]]:
        """Estimate costs across all three cloud providers using cached data."""
        from kube_foresight.pricing.providers.aws import AWSPricingProvider
        from kube_foresight.pricing.providers.azure import AzurePricingProvider
        from kube_foresight.pricing.providers.gcp import GCPPricingProvider

        if not self._cache.all_profiles or not self._cache.recommendations:
            return {}

        result: dict[str, list[CostEstimate]] = {}
        providers = [
            ("aws", AWSPricingProvider()),
            ("gcp", GCPPricingProvider()),
            ("azure", AzurePricingProvider()),
        ]
        for key, prov in providers:
            result[key] = estimate_namespace_costs(
                self._cache.all_profiles, self._cache.recommendations, provider=prov,
            )
        return result
