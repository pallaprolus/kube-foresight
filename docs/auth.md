# Dashboard Authentication

For single-user evaluation, kube-foresight requires no authentication setup — the dashboard runs in **dev mode** and grants Admin access to all requests.

For multi-tenant or team deployments, three roles are supported via API keys.

## Roles

| Role | Landing page | Accessible pages | Permissions |
|------|--------------|------------------|-------------|
| **Executive** | `/executive` | Executive Summary, Costs | Read-only |
| **Engineer** | `/overview` | All analysis pages | Read + write (apply patches) |
| **Admin** | `/executive` | All pages | Full access + audit log |

## Configuration

Set role-specific API keys via environment variables:

```bash
export KF_EXEC_API_KEY=exec-secret
export KF_ENGINEER_API_KEY=eng-secret
export KF_ADMIN_API_KEY=admin-secret
```

Or via Helm values:

```yaml
dashboard:
  execApiKey: exec-secret
  engineerApiKey: eng-secret
  adminApiKey: admin-secret
```

When **none** of these are set, the dashboard runs in dev mode (everyone is Admin). When **any** are set, authentication is enforced for all roles — pass the key as `Authorization: Bearer <key>` or via the `kf-api-key` cookie.

## When you need this

You probably **don't** need this for an initial proof-of-concept. Start with dev mode, validate the recommendations against your workloads, and only enable RBAC once the tool is being shared across teams.
