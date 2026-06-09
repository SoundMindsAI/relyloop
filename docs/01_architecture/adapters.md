# Adapters

**Status:** Adopted. Two implementations ship today: `ElasticAdapter` (handling ES + OpenSearch, MVP1) and `SolrAdapter` (Apache Solr, shipped MVP2 / 2026-05-31 alongside UBI judgments). The supported engines are Elasticsearch, OpenSearch, and Apache Solr. Per-release timing per [`tech-stack.md` §"Canonical release matrix"](tech-stack.md).
**Source of truth for product context:** [docs/00_overview/relyloop-spec.md §8](../00_overview/relyloop-spec.md) ("Engine adapter specification") and §11 ("Search space & parameters").

---

## The architectural rule

**The adapter layer is the only place engine-specific logic lives.** Every other service (study runner, judgment generator, agent, UI) speaks the unified parameter vocabulary defined in §"Cross-engine parameter naming" below. Adapters translate from the unified vocabulary to the native engine API.

Why this matters: a feature that adds, say, a new tuning parameter does so once at the unified layer; every adapter implementation pivots it to its native form. There's no scenario in MVP1+ where engine-specific code lives outside `backend/app/adapters/`.

## The Protocol

Every adapter implements the same `SearchAdapter` Protocol:

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class SearchAdapter(Protocol):
    engine_type: str  # "elasticsearch" | "opensearch" | "solr"

    def health_check(self) -> HealthStatus: ...
    def list_targets(self, *, target_filter: str | None = None) -> list[TargetInfo]: ...
    def get_schema(self, target: str) -> Schema: ...
    def list_query_parsers(self) -> list[str]: ...

    def render(
        self,
        template: QueryTemplate,
        params: dict[str, ParamValue],
        query_text: str,
    ) -> NativeQuery: ...

    def search_batch(
        self,
        target: str,
        queries: list[NativeQuery],
        top_k: int,
        request_id: str | None = None,
    ) -> dict[str, list[ScoredHit]]: ...
    # returns {query_id: [ScoredHit(doc_id, score, _explain?), ...]}

    def explain(
        self,
        target: str,
        query: NativeQuery,
        doc_id: str,
    ) -> ExplainTree: ...

    # Cursor-scan surface (chore_ubi_reader_search_after_pagination Story 1.1)
    async def scan_all(
        self,
        target: str,
        body: dict[str, Any],
        *,
        page_size: int,
        cursor: object | None = None,
        fl: list[str] | None = None,
        request_id: str | None = None,
    ) -> ScanPage: ...
    # Full-stream paginated read; loops until ScanPage.cursor is None.

    async def close_scan(
        self,
        cursor: object | None,
        *,
        request_id: str | None = None,
    ) -> None: ...
    # Release any engine-side resource (e.g. PIT) held by a non-terminal cursor.
```

**Cursor-scan surface (`scan_all` / `close_scan`).** Added by
[`chore_ubi_reader_search_after_pagination`](../00_overview/planned_features/02_mvp2/chore_ubi_reader_search_after_pagination/feature_spec.md)
for the full-traffic UBI aggregation path. Abstracts the two engine
pagination idioms:

- **ES + OpenSearch** — `search_after` over an injected deterministic
  total-order sort `[{timestamp: asc}, {_shard_doc: asc}]`, anchored
  inside a PIT (Point-In-Time). The PIT id rotates with each response;
  the adapter packs the latest id into the opaque cursor so
  continuations carry it forward. Narrow fallback (only on
  405/501/400-unsupported PIT-open) to a no-PIT path that uses a
  configured `Settings.ubi_no_pit_tiebreaker_field`; if no tiebreaker is
  configured, degrades further to a single sampled query bounded by the
  10k result window + WARN log. **Never sorts on `_id`** (ES 9 disables
  `_id` fielddata by default — sorting on it returns 400). The wire
  shape for close differs per engine: ES `DELETE /_pit` body
  `{"id": <pit_id>}`; OpenSearch `DELETE /_search/point_in_time` body
  `{"pit_id": [<pit_id>]}`. The PIT-close paths are **unindexed** —
  required by the read-only invariant (`UbiReader` issues no indexed
  DELETEs).
- **Solr** — `cursorMark` over a uniqueKey-terminated sort. Requests
  **POST** `/solr/<target>/select` with form-encoded body params (NOT
  GET) so large `{!terms f=query_id}` filters don't overflow URL
  limits. Terminal when the engine returns `nextCursorMark` equal to
  the request's cursorMark (or a short page). `close_scan` is a no-op
  — cursorMark holds no server-side resource.

The cursor token is opaque and engine-internal — the caller round-trips
it verbatim. `UbiReader._scan_ubi_events` + `_scan_ubi_queries` consume
this surface page-by-page; the reader's per-call ceiling
(`Settings.ubi_max_events_scan` / `Settings.ubi_max_queries_scan`)
bounds total work and `close_scan` is invoked in a `finally` block on
every exit path so PITs cannot leak beyond their `keep_alive`.

`search_batch` is the **only hot-path method** during a study (called once per Optuna trial). Every other method is define-time (`get_schema`, `list_targets` — called during cluster registration and study creation) or debug-time (`explain` — called from the UI when a user wants to see why a doc ranked where it did).

**Pre-render transform contract** (added by [`feat_query_normalization_tuning`](../00_overview/planned_features/02_mvp2/feat_query_normalization_tuning/feature_spec.md)). The `render()` implementation is permitted to apply a deterministic pure-function transform to `query_text` before injecting it into the Jinja context, provided the transform is recorded in the trial's `params` JSONB as a search-space value the operator declared. The `query_normalizer` key is the reserved canonical instance. Both `ElasticAdapter.render` and `SolrAdapter.render` implement the same pop-and-normalize hook, so the same normalized `query_text` enters the template regardless of engine. As of [`feat_query_normalizer_typed_pipeline`](../00_overview/planned_features/02_mvp2/feat_query_normalizer_typed_pipeline/feature_spec.md) the hook accepts **either** a Phase-1 bundle string (`"lowercase+trim"`) **or** a typed-pipeline powerset label (`"lowercase+strip_punctuation"`) under that key — both resolve through `steps_for_label` → `normalize_pipeline`, so a non-bundle winning label applies correctly rather than raising.

**Per-method exception contract.** Concrete adapter implementations translate engine HTTP status codes to named exceptions so routers can dispatch each to a distinct `error_code` envelope:

| Method | 401/403 | 404 | 5xx / connection failure |
|---|---|---|---|
| `list_targets` | `TargetsForbiddenError` → 403 `TARGETS_FORBIDDEN` (`retryable=false`; UI auto-engages manual mode) | (n/a) | `ClusterUnreachableError` → 503 `CLUSTER_UNREACHABLE` |
| `get_schema` | `ClusterUnreachableError` → 503 `CLUSTER_UNREACHABLE` | `TargetNotFoundError` → 404 `TARGET_NOT_FOUND` | `ClusterUnreachableError` → 503 `CLUSTER_UNREACHABLE` |

The asymmetry on 401/403 (`list_targets` distinguishes; `get_schema` conflates with 5xx) is intentional: ACL-restricted listing has a UX-distinct remediation (manual-mode target entry) that ACL-restricted schema lookup does not have at this point in the wizard. See [`feat_create_study_target_autocomplete`](../00_overview/implemented_features/2026_05_20_feat_create_study_target_autocomplete/) for the rationale.

**`list_targets` filter semantics** (added by [`feat_cluster_target_filter`](../00_overview/implemented_features/2026_05_20_feat_cluster_target_filter/)). When the caller passes `target_filter="<glob>"`, the adapter restricts the result to names where `fnmatch.fnmatchcase(name, glob)` returns True. Glob syntax: `*`, `?`, `[seq]`, `[!seq]` — no brace expansion. Case-sensitive via `fnmatchcase` (avoids platform-dependent `os.path.normcase` in `fnmatch.fnmatch`). **Order of operations:** the engine's system-index `.` exclusion runs FIRST; the glob filter runs SECOND. Operators cannot re-expose `.kibana_1` or similar via a permissive filter. The router resolves `cluster.target_filter` from the DB row before calling the adapter — `target_filter` is per-cluster metadata, not a per-request query parameter.

The Protocol lives in `backend/app/adapters/protocol.py`. Adapter implementations live as siblings (`backend/app/adapters/elastic.py` and `backend/app/adapters/solr.py`).

## ElasticAdapter (MVP1)

A **single** adapter handles both Elasticsearch and OpenSearch. Reasons (per umbrella spec §8 lines 203–211):

- ES and OpenSearch share the same Query DSL — `multi_match`, `function_score`, `bool`, etc. work identically.
- The `_msearch` and `_explain` endpoints exist on both with the same shape.
- Engine-version differences are handled with minor version-aware branches inside the same class.
- Splitting into two near-duplicate classes would create maintenance burden with no architectural benefit.

The adapter selects engine-specific behavior via the `engine_type` flag passed at construction (read from the `clusters` row).

**Implementation notes:**
- `search_batch` uses the `_msearch` API for batch efficiency. Per-query `_search` calls are an anti-pattern.
- `render` produces ES/OpenSearch Query DSL JSON. Jinja templates live under `templates/elasticsearch/` and work against both engines unmodified for the v1 query patterns.
- `explain` calls `_explain`. (MVP1 implements; the UI surface for explain is MVP2.)
- Authentication: `clusters.auth_kind` selects the auth flow:
  - `es_apikey` — `Authorization: ApiKey <base64>`
  - `es_basic`, `opensearch_basic` — HTTP Basic
  - `opensearch_sigv4` — **reserved**, raises `NotImplementedError` in MVP1; AWS managed OpenSearch lands MVP3.

**Engine version support:**
- Elasticsearch 8.11+ and 9.x.
- OpenSearch 2.x (matches ES 7.10 baseline) and 3.x.
- Older versions are explicitly out of scope.

## Cross-engine parameter naming

Templates use **unified parameter names**. The adapter pivots them to native names. This table is the contract; adding a new parameter means extending the unified vocabulary and updating every adapter that supports it.

| Concept | Unified name | ES / OpenSearch (`multi_match`) | Solr (`edismax`) (MVP2) |
|---|---|---|---|
| Per-field weights | `field_boosts: {f: w}` | `fields: ["f^w"]` | `qf=f^w` |
| Phrase fields | `phrase_field_boosts` | nested `phrase` clause | `pf` |
| Tie breaker | `tie_breaker` | `tie_breaker` | `tie` |
| Min should match | `min_should_match` | `minimum_should_match` | `mm` (richer arithmetic syntax — `2<-25% 9<-3`) |
| Fuzziness | `fuzziness` | `fuzziness` | (manual via `~` in query parser) |
| Slop | `slop` | `slop` | `ps` |
| Boost function | `boost_fn: {field, type, params, combine: "add"\|"multiply"}` | `function_score` (multiplicative default; additive when `combine=add`) | `bf` (additive) or `boost` (multiplicative) chosen by `combine` |
| Reranker model | `rerank_model: {id, top_k}` | `rescore.window_size` + LTR | `rq={!ltr model=... reRankDocs=...}` |

**When a concept doesn't exist natively**, the adapter either provides a best-effort translation OR raises `UnsupportedParameter` at render time. The search-space validator catches this before a study runs (rejects the study definition rather than failing trials individually).

An earlier `stage_enabled` unified-vocabulary parameter (a pipeline stage toggle) is not part of the vocabulary; the three supported engines (ES, OpenSearch, Solr) expose query-time knobs, not pipeline stages.

## Authentication and credentials

Credentials never live in the database. The `clusters.credentials_ref` column is a key into a mounted secrets file; the adapter resolves it via the mounted-secrets helper from `infra_foundation`.

| `auth_kind` | Credential file format | MVP1 status |
|---|---|---|
| `es_apikey` | base64-encoded `id:api_key` string | Active |
| `es_basic` | YAML: `{username, password}` | Active |
| `opensearch_basic` | YAML: `{username, password}` | Active |
| `opensearch_sigv4` | YAML: `{access_key_id, secret_access_key, region, role_arn?}` | Reserved; raises `NotImplementedError` until AWS managed OpenSearch is wired up (GA v1 hardening) |
| `solr_basic` | YAML: `{username, password}` | Activates at **MVP2** (Apache Solr adapter) |
| `solr_apikey` | YAML: `{jwt_token, refresh_url?}` for Solr 9+ `JWTAuthPlugin` | Activates at **MVP2** (Apache Solr adapter) |

### SolrAdapter (MVP2 — implemented)

Apache Solr support ships in MVP2 via `backend/app/adapters/solr.py`. Full
scope in
[`infra_adapter_solr`](../00_overview/planned_features/02_mvp2/infra_adapter_solr/).
Summary of the implementation:

- `search_batch` issues parallel `/select` requests via
  `asyncio.gather(..., return_exceptions=True)` with preserved
  `query_id` mapping (Solr has no `_msearch` equivalent). `fl` is
  normalized so `score` AND the resolved `uniqueKey` are always present
  in the response.
- `render` produces a Solr request-parameter dict that mixes Solr-native
  keys (`defType`, `q`, `qf`, `pf`, `tie`, `mm`, `ps`, `bf`, `boost`,
  `rq`, `fl`, ...) with unified cross-engine keys that auto-pivot to
  their Solr equivalents (`field_boosts` → `qf`, `boost_fn{combine:
  add|multiply}` → `bf`/`boost`, `rerank_model` → `rq={!ltr ...}`).
  Canonical templates live at `samples/templates/solr/products_{edismax,
  dismax, lucene}.j2`.
- `get_schema` calls Solr's `/<target>/schema/fields`; `list_targets`
  dispatches on the probe-recorded `engine_config.mode`: cloud →
  `/admin/collections?action=LIST` + per-target `/select?rows=0` for
  doc counts; standalone → `/admin/cores?action=STATUS` reads
  `index.numDocs` directly.
- `explain` uses `debugQuery=true&debug=results` with an `fq` pin on
  the uniqueKey; doc IDs containing Lucene metacharacters
  (`+`, `-`, `:`, `(`, `)`, spaces, ...) are escaped via the
  `_lucene_escape` helper.
- `get_document` uses Solr's RealTime Get (`/<target>/get?id=...`);
  `list_documents` paginates via `cursorMark` with the terminal-page
  rule (when `nextCursorMark == cursorMark`, drop the next-cursor token
  so the router's `has_more` derives False without overfetch).
- LTR rescoring: render-time pre-flight against
  `engine_config.ltr_models` (capability-probe-populated) raises
  `LtrModelNotFoundError` → 400 `LTR_MODEL_NOT_FOUND` when the
  requested model id isn't loaded. Models are uploaded out-of-band via
  Solr's `/schema/model-store`; training stays in the backlog.
- Capability probe (`probe_capabilities()`) records version, mode,
  `ubi_component_present`, `ltr_module_present`, `ltr_models[]`, and
  `unique_key_per_target` into `engine_config`. Re-run via
  `POST /api/v1/clusters/{id}/reprobe`. Two new sister endpoints:
  `POST /clusters/test-connection` (probes an unsaved config; always 200
  with a diagnostic result) and the reprobe itself (concurrent calls
  serialize on `SELECT ... FOR UPDATE`).
- UBI on Solr: the `UbiReader` reads the `ubi_queries` + `ubi_events`
  collections on Solr unchanged, so UBI judgment generation works on Solr
  from day one. The live capture component `solr.UBIComponent` does NOT ship
  in stock Solr images (verified), so the local demo synthesizes those events
  directly; the capability probe reports `ubi_component_present=false`.
- Supported versions: Solr 9.x and 10.x; SolrCloud and standalone
  auto-detected via `/admin/zookeeper/status`.

## Cross-references

- Stack choices (httpx async, Pydantic v2 models for the Protocol): [`tech-stack.md`](tech-stack.md)
- `clusters` table backing the registered clusters: [`data-model.md`](data-model.md)
- API conventions for `/clusters/{id}/...` endpoints: [`api-conventions.md`](api-conventions.md)
- Service topology (where the adapter dispatch happens): [`system-overview.md`](system-overview.md)
- MVP1 feature spec: [`infra_adapter_elastic/feature_spec.md`](../00_overview/implemented_features/2026_05_10_infra_adapter_elastic/feature_spec.md)
- MVP1 navigation summary: [`mvp1-overview.md`](mvp1-overview.md)
