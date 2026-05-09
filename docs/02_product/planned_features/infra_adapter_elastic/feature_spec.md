# Feature Specification — infra_adapter_elastic

**Date:** 2026-05-08 (header status refreshed 2026-05-09)
**Status:** Approved — all open questions resolved (see §19 Decision log: 8 dated entries, the most recent on 2026-05-09 closing out `health_check` TTL, `engine_config.api_version` defaulting, `run_query` `top_k` cap, and the OpenSearch 3.x scope deferral)
**Owners:** TBD
**Related docs:**
- [docs/02_product/mvp1-user-stories.md](../../mvp1-user-stories.md) — covers US-4, US-5, US-6
- [docs/01_architecture/adapters.md](../../../01_architecture/adapters.md) — SearchAdapter Protocol + cross-engine parameter naming
- [docs/01_architecture/data-model.md](../../../01_architecture/data-model.md) — `clusters` and `config_repos` tables (MVP1 shape)
- [docs/01_architecture/api-conventions.md](../../../01_architecture/api-conventions.md) — endpoint conventions this feature follows
- [docs/01_architecture/mvp1-overview.md](../../../01_architecture/mvp1-overview.md) — MVP1 architecture entry point
- [docs/00_overview/product/relevance-copilot-spec.md](../../../00_overview/product/relevance-copilot-spec.md) §19 — agent tools (`get_schema`, `run_query` consumed in `feat_chat_agent`)
- Depends on: [`infra_foundation/feature_spec.md`](../infra_foundation/feature_spec.md)

---

## 1) Purpose

- **Problem:** RelyLoop tunes search relevance against Elasticsearch and OpenSearch clusters. Without an adapter to talk to those engines, no other capability (study runner, judgment generator, agent) can do useful work. The adapter is the entire surface where engine-specific logic lives — see [`adapters.md`](../../../01_architecture/adapters.md) §"The architectural rule."
- **Outcome:** A single `ElasticAdapter` implements the `SearchAdapter` Protocol and serves both Elasticsearch (8.11+ / 9.x) and OpenSearch (2.x / 3.x), distinguished by a `engine_type` column. Relevance engineers can register a cluster, see its schema, and the system can execute a batch of queries against it via `_msearch`.
- **Non-goal:** No Lucidworks Fusion, no Apache Solr — those are MVP3 (Fusion) and v2+ (Solr) per [`adapters.md` §"Reserved for later releases"](../../../01_architecture/adapters.md). No template rendering optimization beyond a working baseline; performance work is deferred to MVP2+.

## 2) Current state audit

**Pre-foundation feature.** `infra_foundation` ships first; this feature lands on top of it. After foundation:

- `backend/app/api/health.py` exists with the `/healthz` endpoint that probes ES + OpenSearch reachability — this feature does not modify it but does add a new `subsystems.elasticsearch_clusters` field once clusters can be registered (the existing `elasticsearch` subsystem probes only the local Compose container; the new field probes user-registered clusters).
- `backend/app/db/` exists with Alembic configured but only the empty `alembic_version` table — this feature adds the first business tables (`clusters`, `config_repos`) per [`data-model.md`](../../../01_architecture/data-model.md).
- No prior adapter code. `backend/adapters/` directory is created by this feature, with the Protocol defined in [`adapters.md`](../../../01_architecture/adapters.md) §"The Protocol."
- No prior `httpx` async-client usage; this feature establishes the convention per [`tech-stack.md` §"Backend"](../../../01_architecture/tech-stack.md).

## 3) Scope

### In scope

- `SearchAdapter` Protocol per [`adapters.md` §"The Protocol"](../../../01_architecture/adapters.md), defined in `backend/adapters/protocol.py` with all six methods: `health_check`, `list_targets`, `get_schema`, `list_query_parsers`, `render`, `search_batch`, `explain`. Type-only `Protocol` with `@runtime_checkable`.
- `ElasticAdapter` per [`adapters.md` §"ElasticAdapter (MVP1)"](../../../01_architecture/adapters.md), implementing the Protocol against ES/OpenSearch in `backend/adapters/elastic.py`. Single class, `engine_type` field selects between ES and OpenSearch behavior where it differs.
- Auth flows per [`adapters.md` §"Authentication and credentials"](../../../01_architecture/adapters.md): `es_apikey`, `es_basic`, `opensearch_basic` active in MVP1. `opensearch_sigv4` reserved (raises `NotImplementedError`); deferred to MVP3.
- `clusters` and `config_repos` tables per [`data-model.md`](../../../01_architecture/data-model.md). Both created in **full MVP1 shape** including `config_repos.webhook_registration_error` (which `feat_github_webhook` later writes to). Per the no-piecemeal-migrations rule in [`data-model.md` §"MVP1 table inventory + migration ownership"](../../../01_architecture/data-model.md), this feature owns these two tables outright; downstream features INSERT/UPDATE rows but do not ALTER the schemas.
- API endpoints:
  - `POST /api/v1/clusters` — register a cluster.
  - `GET /api/v1/clusters` — list registered clusters.
  - `GET /api/v1/clusters/{cluster_id}` — cluster detail (includes `health_check` result).
  - `GET /api/v1/clusters/{cluster_id}/schema?target=<index>` — schema introspection.
  - `POST /api/v1/clusters/{cluster_id}/run_query` — execute one query DSL fragment against an index, return top-K hits with scores. Powers US-6.
- An ES + OpenSearch *seed* command (`make seed-clusters`) that registers the local Compose ES + OpenSearch as cluster rows for tutorial/testing convenience. Idempotent.
- `pytest-recording` cassettes for ES + OpenSearch interactions, per the cassette pattern in [`tech-stack.md` §"Backend"](../../../01_architecture/tech-stack.md). Tests run hermetically against cassettes; the integration-test job re-records against live containers.

### Out of scope

- Lucidworks Fusion adapter, Apache Solr adapter — out per §27.
- AWS SigV4 auth implementation against AWS managed OpenSearch — `auth_kind=opensearch_sigv4` is reserved but raises `NotImplementedError` if a cluster registration uses it. Real implementation in MVP3 (when production-stack adopters arrive).
- Reranker (`rerank_model`), LTR plugin support — out per §27 (not in MVP1 scope; the parameter exists in the unified vocabulary but ElasticAdapter raises `UnsupportedParameter` in MVP1).
- Connection pooling tuning, p99 latency optimization — MVP2+.
- Field-level access control / index-level RBAC — out (single-tenant MVP1).

### API convention check

Follows [`api-conventions.md`](../../../01_architecture/api-conventions.md). All cluster endpoints live under `/api/v1/clusters`; error envelope is the standard structured shape; UUIDv7 IDs per [`data-model.md`](../../../01_architecture/data-model.md) §"Conventions."

### Phase boundaries

Single-phase. ES + OpenSearch ship together; the single-adapter design means there's no "ES first, OpenSearch later" split.

## 4) Product principles and constraints

- **One adapter, two engines.** ES and OpenSearch share the Query DSL; one class handles both with engine_type-aware branches per [`adapters.md` §"ElasticAdapter (MVP1)"](../../../01_architecture/adapters.md). Splitting into two near-duplicate classes is rejected.
- **Hot-path = `search_batch` only.** Every other method is define-time or debug-time. `search_batch` uses `_msearch` for batch efficiency; other methods can be straightforward request/response.
- **Adapter is the engine boundary.** Calling code (study runner, judgment generator) uses unified parameter names from [`adapters.md` §"Cross-engine parameter naming"](../../../01_architecture/adapters.md); adapter pivots to native names. No engine-specific code outside `backend/adapters/`.
- **Cassette-replay first.** Tests against ES/OpenSearch use `pytest-recording` cassettes per [`tech-stack.md` §"Backend"](../../../01_architecture/tech-stack.md). Integration tests against live containers are CI-only and not required for unit-test jobs.
- **Auth via mounted secret refs**, not env vars per [`deployment.md` §"Secrets"](../../../01_architecture/deployment.md). `clusters.credentials_ref` is a key into a mounted secrets file.

### Anti-patterns

- **Do not** create separate `ElasticsearchAdapter` and `OpenSearchAdapter` classes that duplicate the Query DSL handling. The §8 spec is explicit.
- **Do not** put engine-specific logic in `backend/services/` or `backend/api/`. If a study runner needs to know about `_msearch` semantics, the adapter abstraction has leaked — fix the abstraction, not the caller.
- **Do not** call the cluster's `_search` API one query at a time during studies. `_msearch` is the contract for the hot path; per-query calls are a 10× regression in throughput.
- **Do not** rely on environment-variable secrets at the adapter layer. The adapter receives a `credentials_ref` and resolves it via the mounted-secrets helper from `infra_foundation`.

## 5) Assumptions and dependencies

- **Dependency: `infra_foundation` shipped.** Provides Postgres, Alembic, the API skeleton, `httpx` async-client, settings management, `make migrate` workflow.
- **Dependency: ES 9 + OpenSearch 2.18 containers in local Compose** (per `infra_foundation` FR-1).
- **httpx async client.** Adapter uses one shared client per cluster instance with TCP connection pooling.
- **No external services beyond the cluster the adapter is talking to.** Adapter is self-contained within the API process; does not enqueue jobs.
- **Engine version detection** at adapter init — adapter calls `GET /` once and stores the `version.number`. Used to apply minor version branches (e.g., ES 8 vs 9 differences in `_msearch` response shape if any).

## 6) Actors and roles

- Primary actor: Relevance Engineer (registers clusters, inspects schemas, runs ad-hoc queries).
- Role model: Single-tenant, no auth. All registered clusters visible to all users.
- Permission boundaries: N/A.

### Admin control scope checklist

- [ ] Admin UI needed? **No** — no admin model in MVP1.
- [ ] Ceiling enforcement needed? **No.**
- [ ] Override hierarchy documented? **No.**

### RBAC authorization matrix

**N/A — single-tenant MVP1, no auth.**

### Audit-event instrumentation matrix

**N/A — RelyLoop has no audit-events subsystem yet.** Cluster registration / deletion would generate audit events in a multi-tenant system; revisit when audit-events lands.

## 7) Functional requirements

### FR-1: SearchAdapter Protocol defined and documented
- The system **MUST** define `SearchAdapter` as a `@runtime_checkable Protocol` in `backend/adapters/protocol.py` exactly matching the signature in [`adapters.md` §"The Protocol"](../../../01_architecture/adapters.md).
- The system **MUST** export `HealthStatus`, `TargetInfo`, `Schema`, `NativeQuery`, `ScoredHit`, `ExplainTree`, `QueryTemplate`, `ParamValue` as Pydantic models in the same module.
- Notes: protocol is the boundary; future adapters (Fusion, Solr) implement it.

### FR-2: ElasticAdapter handles ES and OpenSearch
- The system **MUST** implement `ElasticAdapter` in `backend/adapters/elastic.py` satisfying `SearchAdapter`.
- The system **MUST** branch on `engine_type` ∈ {`elasticsearch`, `opensearch`} for the small set of behaviors that diverge (e.g., version detection endpoint shape).
- The system **MUST** support auth kinds `es_apikey`, `es_basic`, `opensearch_basic`. `opensearch_sigv4` is a reserved enum value but raises `NotImplementedError("opensearch_sigv4 not supported in MVP1")` if used.
- The system **MUST NOT** implement Fusion or Solr in this feature.

### FR-3: search_batch uses _msearch
- The system **MUST** implement `search_batch(target, queries, top_k, request_id?)` via the `_msearch` API, not parallel `_search` calls.
- The system **MUST** preserve `query_id` mapping between input order and the response dict.
- The system **MUST** propagate `request_id` (when provided) as an `X-Opaque-Id` header for cluster-side log correlation.
- Notes: the hot path for Optuna trial execution (consumed by `infra_optuna_eval` and `feat_study_lifecycle`).

### FR-4: get_schema returns field types and analyzers
- The system **MUST** implement `get_schema(target)` returning `Schema(name, fields=[FieldSpec(name, type, analyzer?, doc_count?)])` derived from `GET /<target>/_mapping` (and `_field_caps` for analyzer detail where available).
- Notes: covers US-5; consumed by the agent's `get_schema` tool (added in `feat_chat_agent`).

### FR-5: Cluster CRUD API
- The system **MUST** expose `POST /api/v1/clusters` accepting `{name, engine_type, environment, base_url, auth_kind, credentials_ref, engine_config?, notes?}` and returning the created cluster.
- The system **MUST** validate `engine_type` ∈ {`elasticsearch`, `opensearch`} and `auth_kind` ∈ {`es_apikey`, `es_basic`, `opensearch_basic`, `opensearch_sigv4`}; reject others with `ENGINE_NOT_SUPPORTED` / `AUTH_KIND_NOT_SUPPORTED`.
- The system **MUST** probe the cluster on registration (`health_check`) and reject with `CLUSTER_UNREACHABLE` if the probe fails.
- The system **MUST** expose `GET /api/v1/clusters` listing all registered clusters.
- The system **MUST** expose `GET /api/v1/clusters/{id}` returning cluster detail with the latest `health_check` result.
- The system **MAY** expose `DELETE /api/v1/clusters/{id}` (soft-delete via `deleted_at`).
- Notes: covers US-4.

### FR-6: Run-query endpoint for debugging
- The system **MUST** expose `POST /api/v1/clusters/{cluster_id}/run_query` accepting `{target: str, query_dsl: dict, top_k: int (default 10)}` and returning `{hits: [{doc_id, score, source}]}`.
- The system **MUST** time-box the request (default 5s; configurable up to 30s) and return `QUERY_TIMEOUT` on exceeded.
- Notes: covers US-6 and the agent's `run_query` tool (added in `feat_chat_agent`).

### FR-7: Seed command for local convenience
- The system **MUST** ship `make seed-clusters` (delegating to `python -m backend.scripts.seed_clusters`) that registers the local ES + OpenSearch from `infra_foundation` Compose as cluster rows named `local-es` and `local-opensearch`.
- The command **MUST** be idempotent — re-running does not duplicate rows or fail.

## 8) API and data contract baseline

### 7.1 Endpoint surface

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `POST` | `/api/v1/clusters` | Register a cluster | `ENGINE_NOT_SUPPORTED`, `AUTH_KIND_NOT_SUPPORTED`, `CLUSTER_UNREACHABLE`, `CLUSTER_NAME_TAKEN` |
| `GET` | `/api/v1/clusters` | List clusters | (none) |
| `GET` | `/api/v1/clusters/{id}` | Cluster detail | `CLUSTER_NOT_FOUND` |
| `DELETE` | `/api/v1/clusters/{id}` | Soft-delete | `CLUSTER_NOT_FOUND` |
| `GET` | `/api/v1/clusters/{id}/schema?target=<index>` | Schema introspection | `CLUSTER_NOT_FOUND`, `TARGET_NOT_FOUND`, `CLUSTER_UNREACHABLE` |
| `POST` | `/api/v1/clusters/{id}/run_query` | Execute one query, return hits | `CLUSTER_NOT_FOUND`, `INVALID_QUERY_DSL`, `QUERY_TIMEOUT`, `CLUSTER_UNREACHABLE` |

### 7.2 Contract rules

- All cluster-not-found responses use 404 with the same body shape as a soft-deleted cluster (anti-enumeration).
- `CLUSTER_UNREACHABLE` is `retryable: true` (transient infra). Other errors are `retryable: false`.
- `run_query` response includes the cluster's `_source` fields verbatim — no field whitelisting in MVP1 (single-tenant install; if the operator can read the cluster, they can see all fields).

### 7.3 Response examples

`POST /api/v1/clusters` success (201):
```json
{
  "id": "01935a8b-1234-7000-8001-abcdef012345",
  "name": "local-es",
  "engine_type": "elasticsearch",
  "environment": "dev",
  "base_url": "http://elasticsearch:9200",
  "auth_kind": "es_basic",
  "engine_config": {"api_version": "9"},
  "notes": null,
  "created_at": "2026-05-08T15:00:00Z",
  "health_check": {"status": "green", "version": "9.0.0", "checked_at": "2026-05-08T15:00:00Z"}
}
```

Error (400 — unsupported engine):
```json
{
  "detail": {
    "error_code": "ENGINE_NOT_SUPPORTED",
    "message": "engine_type must be one of: elasticsearch, opensearch (got: lucidworks_fusion)",
    "retryable": false
  }
}
```

Error (503 — cluster unreachable on registration):
```json
{
  "detail": {
    "error_code": "CLUSTER_UNREACHABLE",
    "message": "Cluster at http://elasticsearch:9200 did not respond within 5s",
    "retryable": true
  }
}
```

### 7.4 Enumerated value contracts

| Field | Accepted values (exact) | Backend source of truth | Frontend call site |
|---|---|---|---|
| `engine_type` | `elasticsearch`, `opensearch` | `backend/adapters/protocol.py` (`EngineType` Literal) | cluster create form (`feat_studies_ui` later) |
| `auth_kind` | `es_apikey`, `es_basic`, `opensearch_basic`, `opensearch_sigv4` | `backend/adapters/elastic.py` (`SUPPORTED_AUTH_KINDS` frozenset) | cluster create form |
| `environment` | `prod`, `staging`, `dev` | `backend/db/models/cluster.py` (`Environment` Literal) | cluster create form |
| `health_check.status` | `green`, `yellow`, `red`, `unreachable` | `backend/adapters/elastic.py` (`HealthStatus.status` enum) | cluster detail page |

### 7.5 Error code catalog

| Code | HTTP Status | Meaning |
|---|---|---|
| `ENGINE_NOT_SUPPORTED` | 400 | `engine_type` not in allowlist |
| `AUTH_KIND_NOT_SUPPORTED` | 400 | `auth_kind` not in allowlist (or reserved-but-unimplemented like `opensearch_sigv4`) |
| `CLUSTER_NAME_TAKEN` | 409 | A cluster with this name already exists (single-tenant uniqueness) |
| `CLUSTER_NOT_FOUND` | 404 | Cluster ID not found or soft-deleted |
| `TARGET_NOT_FOUND` | 404 | Target index does not exist on the cluster |
| `CLUSTER_UNREACHABLE` | 503 | Cluster did not respond within timeout |
| `INVALID_QUERY_DSL` | 400 | Query DSL did not parse on the engine |
| `QUERY_TIMEOUT` | 504 | Query exceeded the request time budget |

## 9) Data model and state transitions

### New tables

Full schemas in [`data-model.md`](../../../01_architecture/data-model.md) §"`clusters`" and §"`config_repos`". This feature implements them per the MVP1 shape documented there (no `tenant_id`, no `created_by`).

**Note on `config_repos`:** added in this feature even though it's only consumed by `feat_github_pr_worker` later. Reduces schema churn — better to land both tables in the first migration than split across two PRs that have to coordinate FKs.

**Note on `clusters`:** the `config_repo_id` and `config_path` columns are added by this feature but are nullable until `feat_github_pr_worker` populates them.

### Required invariants

- `clusters.name` is globally unique (single-tenant).
- `clusters.engine_config` shape matches `clusters.engine_type` (Pydantic validation at API layer; not enforced at DB level).
- `auth_kind=opensearch_sigv4` is a valid enum value but raises at adapter construction time.

### State transitions

- Cluster: `active` → `deleted` (soft-delete via `deleted_at`). Soft-deleted clusters do not appear in `GET /api/v1/clusters` and reject `run_query`/schema requests with 404.

## 10) Security, privacy, and compliance

- **Threats:**
  1. Stored credentials in `clusters.credentials_ref` reveal cluster auth. **Mitigation:** `credentials_ref` is a file-path key; the actual credential lives in a mounted secrets file. The DB never stores the credential value.
  2. `run_query` lets the operator execute arbitrary DSL — could be abused to deplete cluster resources. **Mitigation:** time-budget (5s default), top-K cap (1000), and the operator is the only user (single-tenant install).
  3. Cluster URL injection via crafted `base_url`. **Mitigation:** Validate scheme (`http`, `https` only); validate host is not a private-range IP unless `RELYLOOP_ALLOW_PRIVATE_CLUSTERS=true` env is set (default true in MVP1 for local-laptop convenience; flips to false in MVP3 hardening).
- **Secrets handling:** Per `infra_foundation` — file-mounted secrets via the mounted-secrets helper.
- **Auditability:** N/A — no audit subsystem.
- **Data retention:** Cluster rows are soft-deleted; never auto-purged. Operator can `DELETE` and resurrect by re-registering.

## 11) UX flows and edge cases

The API is consumed by `feat_studies_ui` later; this feature has no UI. The interaction surface in MVP1 is `curl` and the agent's `list_clusters` / `register_cluster` / `run_query` / `get_schema` tools (added in `feat_chat_agent`).

### Edge/error flows

- **Cluster reachable at registration but goes down later.** `GET /api/v1/clusters/{id}` reports `health_check.status = unreachable`; downstream `run_query` returns `CLUSTER_UNREACHABLE`. No automatic re-registration.
- **Cluster auth credentials rotate.** Operator updates the mounted secrets file; next adapter call uses the new credential. No DB write needed.
- **Engine version incompatibility (ES 8.10 — below 8.11 minimum).** `health_check` returns `unreachable` with a clear "engine version 8.10 is below minimum 8.11" message; cluster is registered (so the operator can see the row) but `run_query` returns `CLUSTER_UNREACHABLE`.
- **OpenSearch security plugin enabled but `auth_kind=opensearch_basic`.** Auth fails at first request; surfaced as `CLUSTER_UNREACHABLE` with the underlying 401 in the message.

## 12) Given/When/Then acceptance criteria

### AC-1: Register a local ES cluster

- Given the local Compose ES container is healthy and the API is up.
- When the operator runs `make seed-clusters`.
- Then `local-es` and `local-opensearch` rows exist; `GET /api/v1/clusters` returns both with `health_check.status = green`.

### AC-2: Inspect a schema

- Given an index `products` exists on `local-es` with 1,000 docs and fields `title (text)`, `description (text)`, `category (keyword)`, `price (float)`.
- When the operator hits `GET /api/v1/clusters/<local-es-id>/schema?target=products`.
- Then the response is HTTP 200 with `{ name: "products", fields: [{name: "title", type: "text", analyzer: "standard"}, ...] }` listing all 4 fields.

### AC-3: Run a query

- Given the same `products` index with seeded data.
- When the operator POSTs `{ target: "products", query_dsl: { match: { title: "shirt" } }, top_k: 5 }` to `/run_query`.
- Then the response is HTTP 200 with `hits: [{doc_id, score, source}]` length ≤5, scores in descending order.

### AC-4: Search-batch hits _msearch, not _search per query

- Given a fresh ES container with mtail or pcap monitoring.
- When the adapter is called with `search_batch(target, queries=[q1, q2, q3, q4, q5], top_k=10)`.
- Then exactly one HTTP request to `/_msearch` is made (verified via cassette assertion); not five `/_search` requests.

### AC-5: OpenSearch works identically

- Given a query that worked against ES.
- When the same query DSL is sent to an OpenSearch cluster (registered with `engine_type: opensearch`).
- Then the response shape is identical (same `hits` structure with `doc_id`, `score`, `source`).

### AC-6: Unreachable cluster is rejected at registration

- Given a `base_url` pointing at a port nothing is listening on (e.g., `http://localhost:9999`).
- When the operator POSTs to `/api/v1/clusters`.
- Then the response is HTTP 503 with `error_code: CLUSTER_UNREACHABLE` and the cluster row is NOT created.

### AC-7: Reserved-but-unimplemented auth_kind is rejected

- Given a cluster registration with `auth_kind: opensearch_sigv4`.
- When the request lands.
- Then the response is HTTP 400 with `error_code: AUTH_KIND_NOT_SUPPORTED` and message `"opensearch_sigv4 is reserved but not implemented in MVP1"`.

### AC-8: Soft-delete hides from list, returns 404

- Given a registered cluster `c1`.
- When the operator runs `DELETE /api/v1/clusters/c1`.
- Then subsequent `GET /api/v1/clusters` does not include `c1`; `GET /api/v1/clusters/c1` returns HTTP 404 with `error_code: CLUSTER_NOT_FOUND`; the underlying row still exists with `deleted_at` set.

## 13) Non-functional requirements

- **Performance:** `search_batch` for 50 queries × top_k=10 against a 10K-doc index completes in <2s p99 (local Compose ES). Schema lookup completes in <500ms p99.
- **Reliability:** Adapter handles cluster restart cleanly — connection pool drops dead connections and retries once on `ConnectionError`. After a single retry, errors propagate.
- **Operability:** Adapter logs every `search_batch` invocation with `cluster_id`, `target`, `query_count`, `top_k`, `duration_ms`, `request_id` at INFO level. Failed requests at WARN.
- **Accessibility/usability:** N/A.

## 14) Test strategy requirements

- **Unit tests** (`backend/tests/unit/adapters/`):
  - `test_protocol.py` — `ElasticAdapter` satisfies `isinstance(adapter, SearchAdapter)`.
  - `test_elastic_render.py` — `render(template, params, query_text)` produces the expected ES Query DSL for canonical templates (multi_match + function_score + field_boosts).
  - `test_elastic_engine_branch.py` — engine_type branching works for ES vs OpenSearch where they diverge.
  - `test_auth_kinds.py` — `opensearch_sigv4` raises `NotImplementedError`; supported kinds construct correctly.
- **Integration tests** (`backend/tests/integration/`):
  - `test_elastic_msearch.py` — uses `pytest-recording` cassette of a real `_msearch` against ES 9 container; asserts response parsing and query_id mapping.
  - `test_elastic_schema.py` — cassette-replayed `_mapping` + `_field_caps` against ES + OpenSearch.
  - `test_clusters_api.py` — full create/list/detail/delete flow against the test ES container.
  - `test_seed_clusters_idempotent.py` — `make seed-clusters` run twice produces one `local-es` and one `local-opensearch` row.
- **Contract tests** (`backend/tests/contract/`):
  - `test_clusters_api_contract.py` — request/response shapes match the OpenAPI schema.
  - `test_error_codes.py` — every error code in §7.5 produces the documented HTTP status and response shape.
- **E2E tests** (`web/tests/e2e/`): N/A — no UI in this feature.

## 15) Documentation update requirements

- `docs/01_architecture/adapters.md` already exists and describes the Protocol + one-adapter-two-engines decision; this feature *implements* it. Update if the implementation diverges (e.g., a new auth_kind activates earlier than planned).
- `docs/01_architecture/data-model.md` already documents the `clusters` and `config_repos` tables; this feature ships the migration. Update if column shapes change.
- `docs/02_product/mvp1-user-stories.md`: mark US-4 / US-5 / US-6 as "implemented" when this feature ships.
- `docs/03_runbooks/`: add `cluster-registration.md` — how to register a cluster, troubleshoot reachability, rotate credentials.
- `docs/06_vendor_docs/`: NOT touched by this feature — that section is for engine-specific deep dives that don't fit in `01_architecture` (Fusion auth flows, Solr quirks). MVP1's ES + OpenSearch are well-known enough to live in architecture docs.

## 16) Rollout and migration readiness

- **Feature flags:** None.
- **Migration/backfill:** First migration adding business tables. `clusters` and `config_repos` start empty; `make seed-clusters` populates the two local rows.
- **Operational readiness gates:**
  - `docs/03_runbooks/cluster-registration.md` exists.
  - The seed command works on a fresh Compose stack from a clean `make up`.
- **Release gate:** The agent `list_clusters` and `run_query` tools (added later by `feat_chat_agent`) can call this API without modification.

## 17) Traceability matrix

| FR ID | AC IDs | Planned story IDs (TBD) | Test files | Docs to update |
|---|---|---|---|---|
| FR-1 (Protocol) | AC-1 (indirectly) | TBD | `tests/unit/adapters/test_protocol.py` | `docs/01_architecture/adapters.md` |
| FR-2 (ElasticAdapter ES+OS) | AC-1, AC-5 | TBD | `tests/unit/adapters/test_elastic_engine_branch.py` | `docs/01_architecture/adapters.md` |
| FR-3 (search_batch via _msearch) | AC-4 | TBD | `tests/integration/test_elastic_msearch.py` | `docs/01_architecture/adapters.md` |
| FR-4 (get_schema) | AC-2 | TBD | `tests/integration/test_elastic_schema.py` | `docs/01_architecture/adapters.md` |
| FR-5 (Cluster CRUD) | AC-1, AC-6, AC-7, AC-8 | TBD | `tests/integration/test_clusters_api.py`, `tests/contract/test_clusters_api_contract.py` | `docs/03_runbooks/cluster-registration.md` |
| FR-6 (run_query) | AC-3 | TBD | `tests/integration/test_clusters_api.py` | — |
| FR-7 (seed command) | AC-1 | TBD | `tests/integration/test_seed_clusters_idempotent.py` | `docs/03_runbooks/cluster-registration.md` |

## 18) Definition of feature done

- [ ] All AC-1 through AC-8 pass in CI.
- [ ] All test layers green; ≥80% backend coverage on `backend/adapters/elastic.py` and `backend/api/clusters.py`.
- [ ] `pytest-recording` cassettes committed for ES + OpenSearch interactions.
- [ ] `docs/01_architecture/adapters.md` and `docs/03_runbooks/cluster-registration.md` merged.
- [ ] `make seed-clusters` documented in root README quickstart.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

None — all resolved (see Decision log).

### Decision log

- 2026-05-08 — Single `ElasticAdapter` for ES + OpenSearch (not split classes) — see [`adapters.md` §"ElasticAdapter (MVP1)"](../../../01_architecture/adapters.md).
- 2026-05-08 — `tenant_id` and `created_by` columns omitted for MVP1 — see [`data-model.md` §"Reserved for later releases"](../../../01_architecture/data-model.md).
- 2026-05-08 — Fusion / Solr adapters explicitly out of scope — see [`adapters.md` §"Reserved for later releases"](../../../01_architecture/adapters.md).
- 2026-05-08 — `auth_kind=opensearch_sigv4` reserved but not implemented in MVP1 — defers AWS managed OpenSearch support to MVP3.
- 2026-05-09 — `health_check` cached with **30s TTL** — UI polls `GET /clusters` aggressively; without caching, N clusters × 100ms per probe is wasteful.
- 2026-05-09 — OpenSearch 3.x: **MVP1 tests against 2.18 only**; defer 3.x compatibility testing to MVP2. Documented as a known limitation in the cluster-registration runbook.
- 2026-05-09 — `engine_config.api_version`: **optional at registration; auto-filled from `health_check.version` if missing**.
- 2026-05-09 — `run_query` `top_k` cap: **1000** (FastAPI Pydantic validation rejects above).
