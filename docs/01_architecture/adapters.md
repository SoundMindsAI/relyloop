# Adapters

**Status:** Adopted for MVP1. ElasticAdapter (handling ES + OpenSearch) is the only implementation in MVP1; SolrAdapter ships at MVP2 alongside UBI judgments. Lucidworks Fusion is explicitly dropped (see [`chore_drop_fusion_scope/idea.md`](../02_product/planned_features/chore_drop_fusion_scope/idea.md)) — a community-contributed Fusion adapter remains possible against this Protocol, but the project does not own that direction. Per-release timing per [`tech-stack.md` §"Canonical release matrix"](tech-stack.md).
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
```

`search_batch` is the **only hot-path method** during a study (called once per Optuna trial). Every other method is define-time (`get_schema`, `list_targets` — called during cluster registration and study creation) or debug-time (`explain` — called from the UI when a user wants to see why a doc ranked where it did).

**Per-method exception contract.** Concrete adapter implementations translate engine HTTP status codes to named exceptions so routers can dispatch each to a distinct `error_code` envelope:

| Method | 401/403 | 404 | 5xx / connection failure |
|---|---|---|---|
| `list_targets` | `TargetsForbiddenError` → 403 `TARGETS_FORBIDDEN` (`retryable=false`; UI auto-engages manual mode) | (n/a) | `ClusterUnreachableError` → 503 `CLUSTER_UNREACHABLE` |
| `get_schema` | `ClusterUnreachableError` → 503 `CLUSTER_UNREACHABLE` | `TargetNotFoundError` → 404 `TARGET_NOT_FOUND` | `ClusterUnreachableError` → 503 `CLUSTER_UNREACHABLE` |

The asymmetry on 401/403 (`list_targets` distinguishes; `get_schema` conflates with 5xx) is intentional: ACL-restricted listing has a UX-distinct remediation (manual-mode target entry) that ACL-restricted schema lookup does not have at this point in the wizard. See [`feat_create_study_target_autocomplete`](../00_overview/implemented_features/<date>_feat_create_study_target_autocomplete/) for the rationale.

**`list_targets` filter semantics** (added by [`feat_cluster_target_filter`](../00_overview/implemented_features/<date>_feat_cluster_target_filter/)). When the caller passes `target_filter="<glob>"`, the adapter restricts the result to names where `fnmatch.fnmatchcase(name, glob)` returns True. Glob syntax: `*`, `?`, `[seq]`, `[!seq]` — no brace expansion. Case-sensitive via `fnmatchcase` (avoids platform-dependent `os.path.normcase` in `fnmatch.fnmatch`). **Order of operations:** the engine's system-index `.` exclusion runs FIRST; the glob filter runs SECOND. Operators cannot re-expose `.kibana_1` or similar via a permissive filter. The router resolves `cluster.target_filter` from the DB row before calling the adapter — `target_filter` is per-cluster metadata, not a per-request query parameter.

The Protocol lives in `backend/app/adapters/protocol.py`. Adapter implementations live as siblings (`backend/app/adapters/elastic.py` today; `backend/app/adapters/solr.py` arrives with MVP2).

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

The earlier `stage_enabled` unified-vocabulary parameter (Fusion-specific pipeline stage toggle) was removed when Fusion was dropped — see [`chore_drop_fusion_scope/idea.md`](../02_product/planned_features/chore_drop_fusion_scope/idea.md).

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

## Reserved for later releases

### SolrAdapter (MVP2)

Apache Solr ships in MVP2 alongside UBI judgments. Full scope in [`infra_adapter_solr/idea.md`](../02_product/planned_features/infra_adapter_solr/idea.md). Summary:

- `search_batch` uses parallel `/select` requests with a connection pool (Solr has no `_msearch` equivalent).
- `render` produces a Solr request parameter dict; templates under `templates/solr/` mirror the `templates/elasticsearch/` shape. Supports `edismax` (primary), `dismax`, `lucene` parsers.
- `get_schema` uses Solr's Schema API; `list_targets` selects CoresAdmin (standalone) or CollectionsAdmin (SolrCloud) based on a startup capability probe.
- `explain` uses `debugQuery=true&debug=results`.
- LTR rescoring: applies a pre-existing `MultipleAdditiveTreesModel` (XGBoost-compatible) loaded via Solr's `/schema/model-store` as a rescore stage in a trial. Training is out of scope (LTR training is in the backlog).
- UBI on Solr: Solr ships `solr.UBIComponent` in core writing the same `ubi_queries` + `ubi_events` schema as the OpenSearch UBI plugin. The MVP2 `UbiReader` works on Solr unchanged.
- Supports Solr 9.x and 10.x; SolrCloud and standalone.

## Cross-references

- Stack choices (httpx async, Pydantic v2 models for the Protocol): [`tech-stack.md`](tech-stack.md)
- `clusters` table backing the registered clusters: [`data-model.md`](data-model.md)
- API conventions for `/clusters/{id}/...` endpoints: [`api-conventions.md`](api-conventions.md)
- Service topology (where the adapter dispatch happens): [`system-overview.md`](system-overview.md)
- MVP1 feature spec: [`infra_adapter_elastic/feature_spec.md`](../02_product/planned_features/infra_adapter_elastic/feature_spec.md)
- MVP1 navigation summary: [`mvp1-overview.md`](mvp1-overview.md)
