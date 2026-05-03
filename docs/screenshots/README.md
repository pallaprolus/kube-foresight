# Dashboard Screenshots

The README links to two images in this directory:

- `overview.png` — landing view (executive summary or `/overview`)
- `recommendations.png` — recommendations table with cost deltas

## How to capture

```bash
# 1. Launch with synthetic data (15 deployments, deterministic via seed=42)
kube-foresight dashboard --demo

# 2. Open http://localhost:8080 and capture:
#    /executive       → overview.png        (1440x900, retina if possible)
#    /recommendations → recommendations.png
```

Recommended specs:
- **Width**: 1440px (retina @2x = 2880px)
- **Format**: PNG, lossless
- **Crop**: trim browser chrome
- **Theme**: default (light)

A 30-second asciinema cast of `kube-foresight demo` (saved as `docs/demo.cast` and embedded via [asciinema-player](https://github.com/asciinema/asciinema-player)) is also high-leverage for the README.

> **Note:** these images are referenced by [`README.md`](../../README.md). Until they are committed, the README badges will show broken-image placeholders on GitHub. Capture and commit them before the next release.
