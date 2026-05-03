# Architecture

This document is the contributor-facing map of the codebase: how data flows, where each piece lives, and the conventions to follow when extending it.

## Pipeline

```
Metrics Source (K8s API / Prometheus / Mock)
  → Collector (collector/)
    → ContainerMetrics
      → Analyzer (analyzer/) → DeploymentProfile
        → Recommender (recommender/) → Recommendation
          → Patch Generator + Cost Estimator (pricing/)
        → Forecaster (forecaster/) → DeploymentForecast
  → Dashboard (dashboard/)  ← FastAPI + Jinja2 + HTMX + Chart.js
  → CLI (cli/)              ← Typer + Rich
```

## Directory layout

```
kube_foresight/
├── models.py              # All domain dataclasses and enums
├── exceptions.py          # Custom exception hierarchy
├── alerting.py            # Webhook + Slack alert dispatch
├── audit.py               # SQLite audit trail
├── hpa.py                 # HPA detection + conflict checking
├── scheduler.py           # Background collect/analyze loops
├── logging_config.py      # JSON/text log formatting
├── collector/             # Metric collection backends
│   ├── base.py            #   Abstract BaseCollector
│   ├── k8s.py             #   Kubernetes Metrics API + SQLite
│   ├── prometheus.py      #   Prometheus HTTP API
│   ├── mock.py            #   Synthetic data (15 workload profiles)
│   └── store.py           #   SQLite metrics storage
├── analyzer/              # Statistical profiling
│   ├── profiler.py        #   Profile + classify + rank deployments
│   └── stats.py           #   p95/p99/max + IQR anomaly filtering
├── recommender/           # Right-sizing engine
│   ├── engine.py          #   Orchestrates recommendations
│   ├── strategies.py      #   p95, p99, max strategies
│   └── patch.py           #   YAML patch generation
├── forecaster/            # Trend prediction
│   └── trend.py           #   Linear regression + breach forecasting
├── pricing/               # Cost estimation
│   ├── estimator.py       #   Namespace-level cost calculation
│   └── providers/         #   Cloud pricing providers
│       ├── base.py        #     Abstract BasePricingProvider
│       ├── aws.py         #     AWS EKS pricing (us-east-1, m5)
│       ├── gcp.py         #     GCP GKE pricing (us-central1, e2)
│       └── azure.py       #     Azure AKS pricing (East US, Dv5)
├── cli/                   # CLI interface (Typer)
│   ├── app.py             #   Entry point, registers commands
│   ├── formatters.py      #   Rich tables/panels
│   └── commands/          #   analyze, collect, dashboard, demo, forecast, patch, recommend
└── dashboard/             # Web UI (FastAPI)
    ├── app.py             #   App factory, lifespan, health probes
    ├── service.py         #   AnalysisService (caching layer + multi-cloud)
    ├── serializers.py     #   Dict serialization for API/templates
    ├── routes/api.py      #   REST + HTMX endpoints (incl. namespace discovery)
    ├── routes/pages.py    #   HTML page routes (overview, recommendations, costs + detail)
    ├── static/            #   CSS, JS (Chart.js, HTMX, clipboard, app utilities)
    └── templates/         #   Jinja2 (base, pages, partials)
```

## Conventions

- **Models** — all domain types live in `models.py` as dataclasses, not Pydantic
- **Collectors** — implement `BaseCollector` (`check_connection`, `collect`); factory in `collector/__init__.py`
- **Three modes** — `mock` (demo / CI), `k8s` (Metrics API), `prometheus` (PromQL)
- **Service layer** — `dashboard/service.py` wraps the pipeline with `AnalysisCache`
- **Serializers** — `dashboard/serializers.py` converts dataclasses → dicts for JSON/templates
- **Templates** — Jinja2 with Tailwind CSS classes; HTMX for interactivity
- **Config** — environment variables prefixed `KF_` (see [`charts/kube-foresight/values.yaml`](../charts/kube-foresight/values.yaml))
- **Tests** — mirror source structure under `tests/`; use `mode="mock", seed=42` for deterministic fixtures

## Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `KF_LOG_FORMAT` | `text` or `json` | `text` |
| `KF_MODE` | Collector mode | `k8s` |
| `KF_NAMESPACES` | Comma-separated namespaces | `default` |
| `KF_SCHEDULER_ENABLED` | Enable background scheduler | `false` |
| `KF_COLLECT_INTERVAL` | Seconds between collections | `300` |
| `KF_ANALYSIS_INTERVAL` | Seconds between analyses | `900` |
| `KF_DB_PATH` | SQLite database path | `~/.kube-foresight/metrics.db` |
| `KF_PROMETHEUS_URL` | Prometheus server URL | _(none)_ |
| `KF_WEBHOOK_URL` | Alert webhook endpoint | _(none)_ |
| `KF_SLACK_WEBHOOK_URL` | Slack incoming webhook | _(none)_ |
| `KF_CLOUD_PROVIDER` | Cloud pricing: `aws`, `gcp`, `azure` | `aws` |

## Testing

- 276 tests, all passing
- Run: `python3.10 -m pytest tests/ -v --tb=short`
- Mock collector generates 15 deployments (13 over-provisioned, 2 right-sized) with `seed=42`
- Async tests use `pytest-asyncio` with `mode=strict`
- Dashboard tests use `starlette.testclient.TestClient`

## Dependencies

| Group | Packages |
|-------|----------|
| Core | typer, rich, numpy, requests, pyyaml |
| Dashboard (optional) | fastapi, uvicorn, jinja2, python-multipart |
| Kubernetes (optional) | kubernetes |
| Dev | pytest, pytest-asyncio, pytest-cov, ruff, httpx |

## Git conventions

- Imperative mood, concise commit subjects, focus on "why" in the body
- Branch prefixes: `feature/`, `fix/`, `refactor/`, `docs/`, `build/`
