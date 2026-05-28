# Cluster lifecycle

**Status:** Active for MVP1. The conceptual model for the
`/api/v1/clusters` API surface delivered by `infra_adapter_elastic`.

This doc answers the questions that the per-endpoint reference, the
runbook, and the Protocol shape all assume you already know:

- What is "a cluster" in RelyLoop?
- Why does RelyLoop need to register one?
- What are the 6 cluster endpoints actually for?
- How does this fit into the optimization workflow that ships in
  later MVP1 features?

Read this before [`cluster-registration.md` runbook](../03_runbooks/cluster-registration.md)
(procedural / "do this") or [`adapters.md`](adapters.md) (Protocol /
"the engine boundary"). Both build on the model defined here.

---

## What RelyLoop is, in one paragraph

RelyLoop is an **off-line search-relevance tuning tool**. It does not
host search, does not serve traffic, and does not sit on the live
search-serving path. Your team already runs Elasticsearch / OpenSearch
somewhere (production, staging, AWS, Docker, anywhere). Your engineers
have written queries against it. Some of those queries return bad
results. RelyLoop runs **experiments** against your cluster — sweeping
query-time parameters, scoring weights, analyzers — to find settings
that produce better hits on judged examples. Winning settings come out
as **pull requests against your search-config Git repo**, where your
team reviews and merges them. The cluster never gets schema or mapping
changes from RelyLoop — only query-time parameters.

## What "a cluster" is in this API

A row in RelyLoop's `clusters` table that captures a connection to **your
existing search engine**. Conceptually:

```
name             stable identifier the operator picks (e.g. "prod-search")
engine_type      "elasticsearch" | "opensearch"
environment      "prod" | "staging" | "dev"
base_url         where to reach the engine (e.g. "https://es.acme.com:9200")
auth_kind        which auth flow to use (es_apikey, es_basic, opensearch_basic)
credentials_ref  key into a mounted YAML file that holds the actual creds
engine_config    free-form JSONB (auto-fills `api_version` from the probe)
```

**Credentials are NOT stored in the row.** `credentials_ref` is a *pointer*
into the mounted YAML file at `./secrets/cluster_credentials.yaml`; the
adapter looks them up at request time. This honors CLAUDE.md Rule #2 —
secrets via mounted files, never as DB rows or bare env vars.

The cluster row is **the anchor that downstream features point at**. Every
study you create later names a `cluster_id`; every trial within that study
runs against that cluster; every judgment is scored against the cluster's
returned hits. Without the cluster row, none of the optimization machinery
has a target.

## Why "registration" is its own step

Three reasons RelyLoop doesn't just inline the connection per request:

### 1. Persistence

Studies live for hours to days. They run thousands of trials in the
background. Each trial needs a stable handle for "the cluster this study
is tuning against." That handle is `clusters.id` (UUIDv7). Without
registration, the only alternative would be re-passing URL + credentials
on every API call, which (a) leaks credentials into request bodies, (b)
tangles operator changes (rotating creds requires updating every active
study), (c) makes it impossible for the UI's home screen to render
"clusters this deployment knows about."

### 2. Up-front health + version validation

Registration probes the cluster (`GET /_cluster/health` + `GET /` for
version) before the row gets inserted. If the probe fails — bad URL,
bad credentials, engine version below minimum — the API returns
**503 `CLUSTER_UNREACHABLE` and refuses to insert the row** (AC-6).
This avoids the failure mode of "register a cluster that nobody can
actually talk to, then discover it 200 trials into a study." Engine
version is enforced at the floor (Elasticsearch 8.11+, OpenSearch 2.0+);
older versions are explicitly out of scope.

### 3. Credential isolation

By keeping creds in the mounted YAML rather than the DB:

- DB dumps don't contain secrets.
- Rotating a credential is `vim ./secrets/cluster_credentials.yaml &&
  docker compose restart api` — no DB migration, no API call.
- The cluster row stays the same across credential rotations; studies
  that point at it keep working.

## The lifecycle

```
                 ┌──────────────────────────────────────────────┐
                 │                                              │
                 ▼                                              │
              [absent]                                          │
                 │                                              │
   POST /clusters│ (probe + insert)                             │
                 ▼                                              │
              [active]──── DELETE /clusters/{id}────►[soft-deleted]
                 │                                              │
   GET, schema,  │                                              │
   run_query     │                                              │
                 │   POST /clusters {same name} ◄───────────────┘
                 ▼   (revive — same id, deleted_at cleared)
              [active]
```

* **`[active]`** — `deleted_at IS NULL`; visible in `GET /clusters` list,
  fetchable via `GET /clusters/{id}`, usable by schema + run_query
  endpoints.
* **`[soft-deleted]`** — `deleted_at IS NOT NULL`; hidden from
  `GET /clusters`, returns 404 from `GET /clusters/{id}`, but the row is
  preserved for audit.
* **Revival** (per spec §10): re-`POST /clusters` with the same
  `name` as a soft-deleted row. The service detects the existing row by
  name, clears `deleted_at`, applies the new field values, and returns
  201 with the **original UUID**. This avoids hitting the
  `clusters.name UNIQUE` constraint and lets operators recover from an
  accidental DELETE.

Hard-delete (truly remove the row) is not exposed in MVP1 — the
soft-delete + revive flow handles every operator scenario.

## The 6 endpoints, mapped to operator intent

| Endpoint | Operator question it answers |
|---|---|
| `POST /api/v1/clusters` | "I want RelyLoop to start tuning queries against this engine." |
| `GET /api/v1/clusters` | "What clusters does this RelyLoop deployment know about?" |
| `GET /api/v1/clusters/{id}` | "Show me one cluster — including is it healthy *right now*?" |
| `DELETE /api/v1/clusters/{id}` | "I'm decommissioning this cluster (or this was a mis-registration)." |
| `GET /api/v1/clusters/{id}/schema?target=<index>` | "What fields exist on this index, what types, what analyzers? I'm authoring a query template and need to know what I can boost." |
| `POST /api/v1/clusters/{id}/run_query` | "Sanity-check this raw Query DSL fragment against the cluster — does it actually return hits?" |

The pattern: one *registration* endpoint (POST), one *enumeration*
endpoint (GET list), one *probe* endpoint (GET detail with health),
one *removal* endpoint (DELETE), and two *introspection* endpoints
(schema + run_query) that the relevance engineer uses while authoring
templates. There is no "edit cluster" endpoint — change a cluster by
DELETE + re-POST (which revives the row, per the lifecycle above).

## What you'll do with a registered cluster (forward-looking)

`infra_adapter_elastic` stops at "you have a registered cluster you can
introspect and run ad-hoc queries against." The optimization workflow
arrives in the next features:

| Step | Lands with |
|---|---|
| 1. Register your cluster | `infra_adapter_elastic` (this PR) |
| 2. Wire up Optuna's RDBStorage + ir_measures | `infra_optuna_eval` |
| 3. Define a **study**: pick a target index, write query templates with parameters, define a metric (e.g. nDCG@10), upload judged queries (good-result examples) | `feat_study_lifecycle` |
| 4. Generate **judgments** (LLM-rated query/doc relevance) for the seed query set | `feat_llm_judgments` |
| 5. Run **trials** — each trial = one candidate parameter setting, executed via `search_batch` (the `_msearch` hot path) against your cluster | `feat_study_lifecycle` |
| 6. Surface the digest of winners + open a **PR against your search-config repo** | `feat_digest_proposal` + `feat_github_pr_worker` |
| 7. Your team merges → your CI deploys the new config → real traffic benefits | (your existing infra) |

So cluster registration is step 1 of an 8-step pipeline. It's the
prerequisite that everything else stands on, and it's worth getting
right (which is why it gets up-front health + version probing, error
codes that distinguish "wrong URL" from "wrong auth", and a soft-
delete+revive flow rather than a destructive hard delete).

## What about the `local-es` and `local-opensearch` clusters?

The Compose stack runs Elasticsearch and OpenSearch as local containers
for development. They're *containers* on the dev machine — they're not
production. `make seed-clusters` registers them as cluster rows so you
can exercise the schema + run_query endpoints against something real
without needing AWS or a remote test environment. The default
credentials in `./secrets/cluster_credentials.yaml` (`elastic/changeme`,
`admin/admin`) match the Compose container defaults — they are
well-known local-only credentials, NOT production secrets. Don't paste
those into a real cluster's registration body.

## Cross-references

- [`cluster-registration.md` runbook](../03_runbooks/cluster-registration.md) — copy-pasteable curl commands for every flow above.
- [`adapters.md`](adapters.md) — the `SearchAdapter` Protocol shape; what each adapter method does internally.
- [`api-conventions.md`](api-conventions.md) — error envelope (`{detail: {error_code, message, retryable}}`), cursor pagination format, `X-Total-Count` semantics.
- [`data-model.md`](data-model.md) — the `clusters` table column-by-column.
- Spec [`infra_adapter_elastic/feature_spec.md`](../00_overview/planned_features/infra_adapter_elastic/feature_spec.md) — FRs, ACs, error code catalog, threat model.
- Live OpenAPI: http://localhost:8000/docs (Swagger UI) — try every endpoint from the browser.
