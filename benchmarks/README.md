# Backtest harness

Validates kube-foresight's recommendations against a **held-out future window**
of a real production trace — the standard way right-sizing is evaluated (cf.
Kubernetes VPA and Google Autopilot). It answers the question local clusters
can't: *if we had applied this recommendation, would the workload have breached
it later?*

This directory is **not** part of the shipped package.

## The metric

For each deployment we split its usage chronologically: the first
`--train-fraction` (default 0.7) is the **train** window, the rest is the
**test** window. Recommendations are generated from train only, then scored on
test:

- **violation rate** — fraction of held-out samples that exceed the
  recommendation. Two flavours:
  - *request* breach → CPU contention / scheduling pressure
  - *limit* breach (memory) → **OOM kill** (the dangerous one)
  Lower is safer.
- **savings %** — how much the recommendation shrinks the request.

A good result is **high savings with near-zero violations**. Reporting either in
isolation is misleading — that trade-off is the whole point.

## Quick self-test (no download)

```bash
# Synthetic generator — proves the pipeline end-to-end
python -m benchmarks.backtest --source mock

# Synthetic Alibaba-format fixture committed under fixtures/
python -m benchmarks.backtest --source alibaba --trace-dir benchmarks/fixtures
```

## Running against the real Alibaba trace

1. Download **cluster-trace-v2018** from
   [alibaba/clusterdata](https://github.com/alibaba/clusterdata/blob/master/cluster-trace-v2018/trace_2018.md).
   You need three files in one directory: `machine_meta.csv`,
   `container_meta.csv`, `container_usage.csv`. (`container_usage.csv` is large —
   the harness streams it; use `--max-app-groups` / `--max-usage-rows` to sample.)

2. Run:

```bash
python -m benchmarks.backtest \
  --source alibaba \
  --trace-dir /path/to/alibaba-2018 \
  --max-app-groups 300 \
  --strategies p95,p99,max \
  --headroom 0.20 \
  --violation-threshold 0.05
```

## Units — read before trusting the CPU numbers

The Alibaba trace is normalized, so a couple of assumptions are baked into the
adapter ([`alibaba.py`](alibaba.py)):

- **Violation rate is unit-invariant.** The tool derives the recommendation from
  the usage series itself, so recommendation and usage always share units. Trust
  this number regardless of the assumptions below.
- **Memory** request (`mem_size`) and usage (`mem_util_percent`) are *both*
  percent-of-machine, so memory ratios are correct with no extra input.
  `--machine-mem-gib` only sets the byte scale (the model wants bytes); it
  cancels out of the ratios.
- **CPU** is the sensitive one: request is in absolute cores while usage is
  percent-of-machine, so the adapter joins `machine_meta.cpu_num` to convert.
  If `machine_meta.csv` is missing or a machine isn't found, it falls back to a
  96-core default — which *would* distort CPU ratios. Keep `machine_meta.csv`
  present for correct CPU results.
- **Dollars are out of scope here.** Normalized units can't produce a real bill.
  Validate cost savings separately on a controlled load-test cluster where node
  count actually changes.

## Regenerating the fixture

```bash
python -m benchmarks.fixtures._generate
```
