"""Custom exceptions for kube-foresight."""


class KubeForesightError(Exception):
    """Base exception."""


class CollectorError(KubeForesightError):
    """Raised when metric collection fails."""


class PrometheusConnectionError(CollectorError):
    """Raised when Prometheus is unreachable."""


class PrometheusQueryError(CollectorError):
    """Raised when a PromQL query fails."""


class K8sConnectionError(CollectorError):
    """Raised when the Kubernetes API is unreachable."""


class K8sMetricsError(CollectorError):
    """Raised when a Kubernetes Metrics API query fails."""


class AnalysisError(KubeForesightError):
    """Raised when analysis computation fails."""


class InsufficientDataError(AnalysisError):
    """Raised when there is not enough data for analysis."""
