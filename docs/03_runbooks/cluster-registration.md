# Cluster Registration Runbook

**Status:** Active (lands with `infra_adapter_elastic`, 2026-05-09)
**Audience:** Operators registering a search cluster against RelyLoop.

> **New to RelyLoop?** Read [`docs/01_architecture/cluster-lifecycle.md`](../01_architecture/cluster-lifecycle.md) first — it explains what "a cluster" is, why registration probes the engine before inserting, and how the 6 endpoints map to operator intent. This runbook assumes that conceptual model and focuses on the procedural commands.

---

## Prerequisites

- The RelyLoop stack is up: `make up` ran cleanly, `curl localhost:8000/healthz`
  returns `status: ok`.
- The DB has migration `0002_clusters_config_repos` applied (`make migrate`
  from a fresh stack).
- The cluster you want to register is **reachable from the API container's
  network**:
  - Local Compose ES / OpenSearch are reachable as `http://elasticsearch:9200`
    and `http://opensearch:9200` from inside the API container.
  - External clusters need a hostname or routable IP that the Docker bridge
    network can resolve. If you POST a `base_url` whose host is unreachable,
    you'll see a 503 `CLUSTER_UNREACHABLE` and the cluster row is **not**
    inserted (per AC-6).
- Credentials for the target cluster live in
  `./secrets/cluster_credentials.yaml`, mounted as
  `/run/secrets/cluster_credentials` inside the API container. The file is a
  top-level YAML mapping `{ref: {...}}`; each cluster's `credentials_ref`
  column points to one of these keys.

## Quick start: register the local Compose containers

```bash
make seed-clusters
```

This calls `python -m backend.app.scripts.seed_clusters` inside the API
container and registers two rows: `local-es` and `local-opensearch`. Re-running
is a no-op (existing rows trip `ClusterNameTaken`, which the seed script
treats as success).

`scripts/install.sh` writes the matching credential YAML on first `make up`:

```yaml
local-es:
  username: elastic
  password: changeme
local-opensearch:
  username: admin
  password: admin
```

These are the well-known Compose container defaults — **not production
secrets**.

## Register an external cluster

### 1. Add credentials to the mounted YAML

Edit `./secrets/cluster_credentials.yaml` (chmod 600 — never commit it). For
HTTP Basic auth:

```yaml
prod-search:
  username: elastic
  password: <real-password>
```

For Elasticsearch API key auth:

```yaml
prod-search:
  api_key: <base64-encoded-id:apikey>
```

The exact field name depends on the `auth_kind`:

| auth_kind          | YAML fields                |
|--------------------|----------------------------|
| `es_apikey`        | `api_key`                  |
| `es_basic`         | `username`, `password`     |
| `opensearch_basic` | `username`, `password`     |
| `opensearch_sigv4` | **NOT supported in MVP1**  |

After editing the YAML, restart the API container so settings re-read:

```bash
docker compose restart api
```

### 2. POST `/api/v1/clusters`

```bash
curl -sS -X POST http://localhost:8000/api/v1/clusters \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "prod-search",
    "engine_type": "elasticsearch",
    "environment": "prod",
    "base_url": "https://search.internal.example.com:9200",
    "auth_kind": "es_basic",
    "credentials_ref": "prod-search",
    "engine_config": null,
    "notes": "Primary production search cluster."
  }'
```

Successful response (HTTP 201):

```json
{
  "id": "<uuidv7>",
  "name": "prod-search",
  "engine_type": "elasticsearch",
  "environment": "prod",
  "base_url": "https://search.internal.example.com:9200",
  "auth_kind": "es_basic",
  "engine_config": {"api_version": "9"},
  "notes": "Primary production search cluster.",
  "created_at": "2026-05-09T12:34:56+00:00",
  "health_check": {
    "status": "green",
    "version": "9.4.0",
    "checked_at": "2026-05-09T12:34:56+00:00",
    "error": null
  }
}
```

`engine_config.api_version` is auto-filled from `health_check.version` (the
major-version slot — `"9"` for 9.4.0, `"2"` for OpenSearch 2.18).

### 3. List + verify

```bash
curl -sS http://localhost:8000/api/v1/clusters | jq
```

The new row appears in `data[]`; `X-Total-Count` header reports the active
row count (excludes soft-deleted).

## Troubleshooting

### `503 CLUSTER_UNREACHABLE`

Causes:

1. **Wrong `base_url`** (typo, port closed, host unreachable). Verify
   reachability from inside the api container:
   ```bash
   docker compose exec api curl -sS https://your-host:9200/_cluster/health
   ```
2. **Wrong credentials.** The probe surfaces 401/403 as `unreachable` with
   the HTTP status in the message. Fix the credential YAML, restart api,
   retry.
3. **Engine version below minimum.** ES < 8.11 or OpenSearch < 2.0 are
   rejected with `engine version X is below minimum Y` in the error
   message. Upgrade the cluster.

The cluster row is **NOT** inserted when registration probes return
`unreachable` (AC-6). Re-POST after fixing the underlying issue.

### `400 AUTH_KIND_NOT_SUPPORTED`

`opensearch_sigv4` (AWS managed OpenSearch + IAM) is reserved for MVP3 — the
DB CHECK accepts it but the adapter rejects construction. Use
`opensearch_basic` (master user) for MVP1, or wait for the v0.3 release.

### `409 CLUSTER_NAME_TAKEN`

A cluster with that `name` is already registered. Either:

* Use a different `name`, OR
* Soft-delete the existing row (`DELETE /api/v1/clusters/{id}`) and re-POST
  — the registration service detects the soft-deleted row by name and
  revives it with the new field values (per spec §10).

### Soft-deleted rows linger

`DELETE /api/v1/clusters/{id}` is a soft delete (sets `deleted_at`). The row
is hidden from `GET /clusters` and `GET /clusters/{id}` but the unique
`name` constraint still applies. To fully remove a row before re-registering
with the same name, see the resurrection path above — it's the standard
operator workflow.

## Rotating credentials

1. Update `./secrets/cluster_credentials.yaml` with the new credential
   value (preserve the `credentials_ref` key the cluster row already
   points at).
2. Restart the api container so the next probe picks up the new YAML:
   `docker compose restart api`.
3. Force a fresh health probe by waiting 30s (Redis cache TTL) or
   manually flushing the cache key:
   `docker compose exec redis redis-cli DEL cluster:health:{cluster_id}`.

The cluster row itself doesn't need updating — only the mounted YAML changes.

## OpenSearch 3.x — known limitation (Decision Log 2026-05-09)

OpenSearch 3.x dropped some legacy ES API compatibility shims that
RelyLoop's adapter relies on for the `_msearch` + `_explain` endpoints.
MVP1 supports OpenSearch 2.x (tested against 2.18.0). 3.x compatibility is
on the MVP3 backlog as part of the production-stack epic.

## See also

- [`docs/01_architecture/adapters.md`](../01_architecture/adapters.md) — the
  `SearchAdapter` Protocol shape.
- [`docs/02_product/planned_features/infra_adapter_elastic/feature_spec.md`](../02_product/planned_features/infra_adapter_elastic/feature_spec.md)
  — the feature spec, FRs, ACs.
- CLAUDE.md Absolute Rule #4 — engine adapter Protocol enforcement.
- `docs/03_runbooks/local-dev.md` — first-run setup, including the
  `make seed-clusters` step.
