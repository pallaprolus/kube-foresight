# kube-foresight

Predictive Resource Optimizer for Kubernetes. Identifies over-provisioned deployments and generates right-sizing patches to reduce cloud spend.

## The Problem

Teams massively over-provision Kubernetes resources out of fear of outages — setting CPU/memory requests based on guesswork. This leads to **40-70% wasted cloud spend** across most clusters.

**kube-foresight** analyzes actual resource usage from Prometheus, identifies the most over-provisioned deployments, and generates kubectl-ready YAML patches with cost savings estimates.

## Features

- Analyzes CPU and memory usage patterns from Prometheus metrics
- Identifies and ranks the most over-provisioned deployments
- Generates right-sizing recommendations with configurable strategies (p95, p99, max)
- Produces kubectl-ready YAML strategic merge patches
- Estimates monthly/annual cost savings (AWS pricing)
- Includes a **demo mode** with synthetic data — no cluster needed to try it out
- Confidence levels based on data quality and variance

## Quick Start

### Install

```bash
pip install -e .
```

### Try the Demo (No Cluster Needed)

```bash
kube-foresight demo
```

This generates synthetic metrics for 15 deployments and runs the full analysis pipeline.

### Generate Patches

```bash
kube-foresight demo --output-dir ./patches
```

### With a Real Prometheus Instance

```bash
# Analyze a namespace
kube-foresight analyze -n production -p http://prometheus:9090

# Get recommendations with cost estimates
kube-foresight recommend -n production -p http://prometheus:9090

# Generate YAML patches
kube-foresight patch -n production -p http://prometheus:9090 -o ./patches

# Apply a patch
kubectl apply -f ./patches/api-gateway-patch.yaml
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `demo` | Full pipeline with synthetic data |
| `analyze` | Identify over-provisioned deployments |
| `recommend` | Generate right-sizing recommendations + cost estimates |
| `patch` | Generate YAML patches for kubectl apply |

### Common Options

| Option | Description | Default |
|--------|-------------|---------|
| `--namespace, -n` | Kubernetes namespace | required |
| `--prometheus-url, -p` | Prometheus base URL | required |
| `--strategy, -s` | Percentile strategy: p95, p99, max | p95 |
| `--headroom` | Safety margin (0.0-1.0) | 0.20 |
| `--top` | Number of top deployments to analyze | 10 |
| `--lookback` | Hours of historical data | 168 (7 days) |

## Architecture

```
Prometheus / Mock Data
        │
        ▼
   ┌─────────┐     ┌──────────┐     ┌──────────────┐
   │Collector │────▶│ Analyzer │────▶│ Recommender  │
   └─────────┘     └──────────┘     └──────┬───────┘
                                           │
                    ┌──────────┐     ┌──────▼───────┐
                    │ Pricing  │◀────│    Engine     │
                    └──────────┘     └──────┬───────┘
                                           │
                                    ┌──────▼───────┐
                                    │  CLI Output  │
                                    │  + Patches   │
                                    └──────────────┘
```

## How It Works

1. **Collect** — Fetches container CPU/memory time-series from Prometheus (or generates synthetic data in demo mode)
2. **Analyze** — Computes usage statistics (mean, p50, p95, p99, max) and calculates an over-provisioning score per deployment
3. **Recommend** — Generates right-sized resource values using the chosen percentile strategy + safety headroom
4. **Estimate** — Calculates cost savings based on cloud provider rates
5. **Output** — Renders Rich terminal tables and/or writes YAML patches

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run with coverage
pytest --cov=kube_foresight
```

## License

Apache License 2.0
