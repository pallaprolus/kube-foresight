# kube-foresight

**Right-size your Kubernetes deployments, forecast resource trends, and estimate the multi-cloud cost impact — in one tool, with kubectl-ready patches.**

[![CI](https://github.com/pallaprolus/kube-foresight/actions/workflows/ci.yml/badge.svg)](https://github.com/pallaprolus/kube-foresight/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![PyPI](https://img.shields.io/pypi/v/kube-foresight.svg)](https://pypi.org/project/kube-foresight/)
[![Status](https://img.shields.io/badge/status-alpha-orange.svg)](#status)

![Dashboard overview](docs/screenshots/overview.png)

## Why kube-foresight?

Most teams over-provision Kubernetes by 40–70% out of fear of outages — and fixing it usually means stitching several tools together: one to recommend new resources, another to apply them, another to watch for future breaches, another to price the change.

kube-foresight runs that whole loop in a single CLI and dashboard:

> **recommendation → kubectl-ready patch → breach forecast → multi-cloud cost**

You get the patch to apply, a prediction of when usage will breach current limits, and the capacity you'd reclaim priced across AWS / GCP / Azure — from one tool instead of four.

## Status

**Alpha — actively developed, not yet battle-tested in production.** Reports, issues, and PRs welcome. See [CHANGELOG / releases](https://github.com/pallaprolus/kube-foresight/releases).

## Try it in 30 seconds (no cluster needed)

```bash
pip install "kube-foresight[dashboard]"
kube-foresight demo                 # full pipeline against synthetic data
kube-foresight dashboard --demo     # web UI at http://localhost:8080
```

![Recommendations view](docs/screenshots/recommendations.png)

## Use it on a real cluster

```bash
# 1. Identify over-provisioned deployments (Metrics API or Prometheus)
kube-foresight analyze   -n production --mode k8s
kube-foresight recommend -n production --mode prometheus -p http://prometheus:9090

# 2. Generate kubectl-ready patches
kube-foresight patch -n production --mode k8s -o ./patches
kubectl apply -f ./patches/api-gateway-patch.yaml

# 3. Forecast when usage will breach current limits
kube-foresight forecast -n production --mode k8s
```

## What's in the box

- **Three collectors** — Kubernetes Metrics API, Prometheus, or mock (for demo / CI)
- **Statistical right-sizing** — p95 / p99 / max strategies (p99 default) with configurable headroom, sizing CPU and memory independently on raw usage so demand spikes aren't discarded
- **Forecasting** — linear regression on historical usage with breach-time prediction and risk classification
- **Multi-cloud cost estimation** — prices the CPU/memory you'd reclaim at approximate on-demand rates for AWS / GCP / Azure
- **Patch generator** — strategic-merge YAML you can `kubectl apply`
- **Web dashboard** — FastAPI + HTMX + Chart.js (overview, recommendations, cost comparison)
- **HPA conflict detection** — refuses to recommend changes that fight your autoscaler
- **Production plumbing** — Dockerfile, Helm chart, health probes, structured JSON logs, optional Slack alerts

> **How costs are calculated:** figures reflect reclaimable capacity — the difference between current and recommended **requests**, priced at approximate blended on-demand rates for the selected provider. Translating reclaimed capacity into billing changes depends on node consolidation by the cluster autoscaler; pair with Kubecost/OpenCost for allocation-accurate spend.

## Where it fits

Several tools cover individual pieces of this well:

- **[KRR](https://github.com/robusta-dev/krr)** — Prometheus-based right-sizing recommendations.
- **[Goldilocks](https://github.com/FairwindsOps/goldilocks)** — surfaces VPA recommendations across a cluster.
- **[VPA](https://github.com/kubernetes/autoscaler/tree/master/vertical-pod-autoscaler)** — in-cluster vertical autoscaling that can apply changes automatically.
- **[Kubecost / OpenCost](https://www.opencost.io/)** — allocation-accurate cost monitoring and spend reporting.

kube-foresight's niche is bringing right-sizing, breach forecasting, kubectl patch output, and side-by-side multi-cloud pricing into one workflow. If KRR already covers your recommendations and Kubecost your spend, you may not need it — it's for teams who'd rather run one loop than wire several tools together.

## CLI reference

| Command | Purpose |
|---------|---------|
| `demo` | Full pipeline with synthetic data — no cluster required |
| `analyze` | Identify over-provisioned deployments |
| `collect` | Snapshot metrics into SQLite for trend analysis |
| `recommend` | Right-sizing recommendations + cost estimates |
| `patch` | Generate kubectl-applyable YAML patches |
| `forecast` | Predict resource trends and breach timelines |
| `dashboard` | Launch the web UI |

Common flags: `--namespace/-n`, `--mode/-m {mock,k8s,prometheus}`, `--prometheus-url/-p`, `--strategy/-s {p95,p99,max}`, `--headroom 0.20`, `--top 10`, `--lookback 168`.

## Deployment

### Docker

```bash
# Pull the published image (GitHub Container Registry)
docker run -p 8080:8080 ghcr.io/pallaprolus/kube-foresight:latest \
  dashboard --host 0.0.0.0 --port 8080 --demo

# …or build from source
docker build -t kube-foresight .
docker run -p 8080:8080 kube-foresight dashboard --host 0.0.0.0 --port 8080 --demo
```

### Helm

```bash
helm install kube-foresight charts/kube-foresight \
  --set collector.mode=k8s \
  --set collector.namespaces=production \
  --set scheduler.enabled=true
```

See [`charts/kube-foresight/values.yaml`](charts/kube-foresight/values.yaml) for persistence, ingress, alerting, and authentication options.

## Configuration

All settings are environment variables prefixed `KF_`:

| Variable | Purpose | Default |
|----------|---------|---------|
| `KF_MODE` | Collector mode (`mock`, `k8s`, `prometheus`) | `k8s` |
| `KF_NAMESPACES` | Comma-separated namespaces | `default` |
| `KF_CLOUD_PROVIDER` | Pricing source: `aws`, `gcp`, `azure` | `aws` |
| `KF_SCHEDULER_ENABLED` | Background collect/analyze loop | `false` |
| `KF_COLLECT_INTERVAL` | Collection interval (seconds) | `300` |
| `KF_ANALYSIS_INTERVAL` | Analysis interval (seconds) | `900` |
| `KF_SLACK_WEBHOOK_URL` | Slack alerts for at-risk deployments | — |
| `KF_LOG_FORMAT` | `text` or `json` | `text` |

## Development

```bash
git clone https://github.com/pallaprolus/kube-foresight && cd kube-foresight
pip install -e ".[k8s,dashboard,dev]"
pytest tests/ -v --tb=short        # 251 tests
ruff check .
helm lint charts/kube-foresight
```

For codebase layout, conventions, and the data-flow diagram, see [`docs/architecture.md`](docs/architecture.md).

## Contributing

Issues and PRs are very welcome — particularly: real-world deployment reports, additional pricing providers, and validation of forecast accuracy on production traces. See [`CONTRIBUTING.md`](CONTRIBUTING.md) once filed.

## License

Apache License 2.0
