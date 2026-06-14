# Adoption Playbook

A short, honest checklist for getting kube-foresight from "interesting repo" to "actually used by other people." Maintainer-facing.

## Discovery checks (do first, before optimizing anything)

Run these to establish the current adoption baseline:

1. **GitHub Insights → Traffic (last 14 days)** — clones, unique visitors, referrers. If 90% of referrers are LinkedIn / Medium / a personal blog, the audience is "people who already know the author," not adopters.
2. **GitHub code search** for `kube-foresight` and `kube_foresight` (code, not repos). Any matches in `requirements.txt`, `Dockerfile`, `Chart.yaml`, or import statements = real users.
3. **Verbatim Google search** for `"kube-foresight"` outside owned domains.
4. **Container registry pulls** if the image is pushed to ghcr.io.
5. **Issues opened by non-author accounts** — the most reliable signal.

## Highest-leverage adoption fixes

Ordered by ROI:

### 1. ✅ PyPI — already shipped

`kube-foresight==0.2.0` is live: <https://pypi.org/project/kube-foresight/>. `pip install kube-foresight` works today. The `publish.yml` workflow is OIDC-configured to release on each `v*` tag, so subsequent releases just need:

```bash
# bump version in pyproject.toml, then:
git tag v0.3.0 && git push origin v0.3.0
```

### 2. Capture the screenshots referenced in the README

See [`screenshots/README.md`](screenshots/README.md). The README currently links to `docs/screenshots/overview.png` and `docs/screenshots/recommendations.png` — both need to be committed for first impressions to land.

A short asciinema cast of `kube-foresight demo` is also high-leverage.

### 3. Push a Docker image to ghcr.io

The Dockerfile is already in place. Add a workflow that builds and pushes `ghcr.io/pallaprolus/kube-foresight:<tag>` on release. This means people can `docker run` without cloning.

### 4. Lead with the value, keep the comparison light

The README leads with the workflow — one loop from recommendation → patch → forecast → cost — and keeps a short "Where it fits" section that credits KRR / Goldilocks / VPA / Kubecost for what each does well. Anchor the pitch on the integrated workflow rather than a feature-by-feature scorecard; a checkbox grid goes stale every time a competitor ships a release and reads as a follower's framing.

- Describe what each tool is best at, not a checkbox grid — it ages better and stays fair.
- If a real differentiator emerges from user feedback (e.g. "the multi-cloud cost view is what made us pick this"), promote that into the headline sentence.

### 5. Write one *result* post, not an announcement post

Generic launch posts on r/kubernetes get downvoted. A post titled *"I right-sized our prod cluster and saved $X/month — here's the open-source tool I used"* with concrete before/after numbers performs an order of magnitude better.

Channels to consider, in priority order:
- r/kubernetes (technical, high-signal)
- r/devops
- Hacker News (Show HN — only when screenshots and a live demo are ready)
- CNCF Slack `#sig-finops` channel
- Kubernetes Podcast / talks

### 6. Stand up a live demo

Streamlit Cloud / Fly.io / Render free tier can host the dashboard with mock data. A clickable URL in the README converts dramatically better than "clone and pip install."

## Things to *not* do

- **Don't add more features before the above.** The repo already has more surface area than current adoption justifies. Engineering energy now is best spent on docs, demos, and distribution.
- **Don't build enterprise features (SSO, multi-tenant, audit) until at least one team is asking for them.** RBAC is already arguably premature.
- **Don't claim production-readiness in the README.** "Alpha — actively developed" is honest and lowers the bar for first issue filers.

## Re-evaluation checkpoint

If, after a real promotion push (PyPI release + screenshots + one r/kubernetes post), the repo still has:

- 0 external clones with referrers from the wild
- 0 issues from non-author accounts
- 0 code-search hits in third-party repos

…then the gap is product-market fit, not exposure. Either re-scope toward a sharper differentiator or wind it down. **More features will not fix a positioning problem.**
