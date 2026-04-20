# kube-foresight

Predictive Resource Optimizer for Kubernetes. Identifies over-provisioned deployments, generates right-sizing patches, forecasts resource trends, and estimates multi-cloud cost savings.

## The Problem

Teams massively over-provision Kubernetes resources out of fear of outages — setting CPU/memory requests based on guesswork. This leads to **40-70% wasted cloud spend** across most clusters.

**kube-foresight** analyzes actual resource usage, identifies the most over-provisioned deployments, and generates kubectl-ready YAML patches with cost savings estimates.

## Features

- **Multi-source collection** — Kubernetes Metrics API, Prometheus, or mock data (no cluster needed)
- **Statistical profiling** — p95/p99/max analysis with IQR anomaly filtering
- **Right-sizing recommendations** — configurable strategies with confidence levels
- **YAML patch generation** — kubectl-ready strategic merge patches
- **Resource forecasting** — linear regression trends with breach prediction and risk classification
- **Multi-cloud cost estimation** — AWS, GCP, and Azure pricing comparison
- **Web dashboard** — FastAPI + HTMX with real-time analysis and Chart.js visualizations
- **Executive dashboard** — single-page KPI summary for leadership with cloud cost comparison
- **Role-based access** — Executive, Engineer, and Admin roles with API key authentication
- **Background scheduler** — continuous collection and analysis with configurable intervals
- **Alerting** — webhook and Slack notifications for at-risk deployments
- **HPA conflict detection** — warns when recommendations conflict with autoscaler targets
- **Audit trail** — SQLite-backed log of all analysis runs and patch applications
- **Production ready** — Dockerfile, Helm chart, health probes, structured logging

## Quick Start

### Install

```bash
pip install -e ".[dashboard]"
```

### Try the Demo (No Cluster Needed)

```bash
# CLI demo — full pipeline with synthetic data
kube-foresight demo

# Web dashboard with demo data
kube-foresight dashboard --demo
```

### With a Real Cluster

```bash
# Analyze using Kubernetes Metrics API
kube-foresight analyze -n production --mode k8s

# Analyze using Prometheus
kube-foresight analyze -n production --mode prometheus -p http://prometheus:9090

# Get recommendations with cost estimates
kube-foresight recommend -n production --mode k8s

# Generate YAML patches
kube-foresight patch -n production --mode k8s -o ./patches

# Apply a patch
kubectl apply -f ./patches/api-gateway-patch.yaml

# Forecast resource trends
kube-foresight forecast -n production --mode k8s
```

### Web Dashboard

```bash
# Basic dashboard
kube-foresight dashboard --demo

# Continuous monitoring with Slack alerts
kube-foresight dashboard \
  --continuous \
  --mode k8s \
  --namespaces production,staging \
  --slack-webhook-url https://hooks.slack.com/services/...
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `demo` | Full pipeline with synthetic data |
| `analyze` | Identify over-provisioned deployments |
| `collect` | Collect and store metrics to SQLite |
| `recommend` | Generate right-sizing recommendations + cost estimates |
| `patch` | Generate YAML patches for kubectl apply |
| `forecast` | Predict resource trends and breach timelines |
| `dashboard` | Launch the web dashboard |

### Common Options

| Option | Description | Default |
|--------|-------------|---------|
| `--namespace, -n` | Kubernetes namespace | `default` |
| `--mode, -m` | Collector: `mock`, `k8s`, `prometheus` | `k8s` |
| `--prometheus-url, -p` | Prometheus base URL | — |
| `--strategy, -s` | Sizing strategy: `p95`, `p99`, `max` | `p95` |
| `--headroom` | Safety margin (0.0–1.0) | `0.20` |
| `--top` | Number of top deployments | `10` |
| `--lookback` | Hours of historical data | `168` (7 days) |

## Role-Based Access Control

Three roles control dashboard access via API keys:

| Role | Landing | Accessible Pages | Permissions |
|------|---------|-------------------|-------------|
| Executive | `/executive` | Executive Summary, Costs | Read-only |
| Engineer | `/overview` | All analysis pages | Read + Write |
| Admin | `/executive` | All pages | Full access + audit |

Set role-specific API keys via environment variables:

```bash
export KF_EXEC_API_KEY=exec-secret
export KF_ENGINEER_API_KEY=eng-secret
export KF_ADMIN_API_KEY=admin-secret
```

When no API keys are configured, all users get Admin access (dev mode).

## Architecture

```
Metrics Source (K8s API / Prometheus / Mock)
  → Collector (SQLite persistence)
    → Analyzer (statistical profiling)
      → Recommender (right-sizing engine)
        → Patch Generator + Cost Estimator
      → Forecaster (trend prediction + risk)
  → Dashboard (FastAPI + HTMX)
  → CLI (Typer + Rich)
  → Alerts (Webhook + Slack)
```

## Deployment

### Docker

```bash
docker build -t kube-foresight .
docker run -p 8080:8080 kube-foresight dashboard --host 0.0.0.0 --port 8080 --demo
```

### Helm

```bash
helm install kube-foresight charts/kube-foresight \
  --set collector.mode=k8s \
  --set collector.namespaces=production \
  --set dashboard.adminApiKey=your-secret-key \
  --set scheduler.enabled=true
```

See `charts/kube-foresight/values.yaml` for all options including persistence, ingress, alerting, and role-based API keys.

## Configuration

All configuration is via `KF_` environment variables. Key options:

| Variable | Purpose | Default |
|----------|---------|---------|
| `KF_MODE` | Collector mode | `k8s` |
| `KF_NAMESPACES` | Comma-separated namespaces | `default` |
| `KF_CLOUD_PROVIDER` | Pricing: `aws`, `gcp`, `azure` | `aws` |
| `KF_SCHEDULER_ENABLED` | Background scheduler | `false` |
| `KF_COLLECT_INTERVAL` | Collection interval (seconds) | `300` |
| `KF_ANALYSIS_INTERVAL` | Analysis interval (seconds) | `900` |
| `KF_WEBHOOK_URL` | Alert webhook endpoint | — |
| `KF_SLACK_WEBHOOK_URL` | Slack incoming webhook | — |
| `KF_LOG_FORMAT` | Log format: `text`, `json` | `text` |

## Development

```bash
# Install with all extras
pip install -e ".[k8s,dashboard,dev]"

# Run tests (276 tests)
pytest tests/ -v --tb=short

# Lint
ruff check .

# Helm chart
helm lint charts/kube-foresight
```

## License

Apache License 2.0
