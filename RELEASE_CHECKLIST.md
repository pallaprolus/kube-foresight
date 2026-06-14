# Release checklist

What "ready to publish" means for this project. The automatable items are
enforced by the [release gate](.github/workflows/release-gate.yml) — a tagged
release **cannot publish** unless they pass. The judgment items are not
mechanically enforceable; review them (or run the `release-check` skill) before
tagging.

## Automated gate (enforced — see release-gate.yml)

- [ ] Tests pass (`pytest`)
- [ ] Lint clean (`ruff check .`)
- [ ] Package builds (`python -m build` → sdist + wheel)
- [ ] **Clean-room install works** — the built *wheel* installs into a fresh
      venv and the app actually runs (CLI entry point + dashboard serves
      `/healthz` and a static asset). This is the check that catches packaging
      bugs editable installs hide.

## Judgment review (not automatable — check before tagging)

**README**
- [ ] Leads with the value / what it does, not a competitor feature-scorecard
      (scorecards go stale and read as a follower's framing)
- [ ] Every claim is currently true — no stale features, accurate test counts,
      accurate config/flags/defaults
- [ ] Maturity label is honest (don't claim production-ready before it is); for
      early projects, pair "alpha" with why it's safe to try
- [ ] Primary path targets the real user (operators get cluster usage first;
      demos are a secondary "try it" aside, not the headline)

**Honest framing**
- [ ] Quantitative claims (savings %, benchmarks, accuracy) are backed by
      reproducible evidence, or are not stated as headline numbers
- [ ] Results/cost are framed as what they actually measure, not inflated
      (e.g. "reclaimable capacity," not "guaranteed bill reduction")
- [ ] Comments and docs are professional and factual — implicitly honest, not
      explicitly editorializing ("trust me," "to be honest," "not misleading")

**Mechanics**
- [ ] Version bumped in `pyproject.toml` (and it isn't already on PyPI)
- [ ] Release notes / changelog written
- [ ] Any new runtime data files are declared as `package-data` (verify they're
      in the wheel, not just the source tree)

## Cutting the release

```bash
# main is green and the judgment review is done
gh release create vX.Y.Z --target main --title "vX.Y.Z" --notes "…"
```

The tag triggers the [Publish](.github/workflows/publish.yml) workflow: the gate
runs first, then PyPI (trusted publisher) and the GHCR image. Watch it:

```bash
gh run watch "$(gh run list --workflow=publish.yml -L 1 --json databaseId -q '.[0].databaseId')"
```

Then confirm the published artifact in a fresh environment before announcing.
