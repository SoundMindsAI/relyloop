# Adapters

**Status:** Adopted for MVP1. ElasticAdapter (handling ES + OpenSearch) is the only implementation in MVP1; Lucidworks Fusion ships at MVP3; Apache Solr at v2+. Per-release timing per [`tech-stack.md` §"Canonical release matrix"](tech-stack.md).
**Source of truth for product context:** [docs/00_overview/product/relevance-copilot-spec.md §8](../00_overview/product/relevance-copilot-spec.md) ("Engine adapter specification") and §11 ("Search space & parameters").

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
    engine_type: str  # "elasticsearch" | "opensearch" | "lucidworks_fusion" | "solr"

    def health_check(self) -> HealthStatus: ...
    def list_targets(self) -> list[TargetInfo]: ...
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

The Protocol lives in `backend/app/adapters/protocol.py`. Adapter implementations live as siblings (`backend/app/adapters/elastic.py`, future `backend/app/adapters/fusion.py`, etc.).

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

| Concept | Unified name | ES (`multi_match`) | Lucidworks Fusion (MVP3) | Solr (`edismax`) (v2+) |
|---|---|---|---|---|
| Per-field weights | `field_boosts: {f: w}` | `fields: ["f^w"]` | stage param `searchFields.fields` or `params.solr.qf` override | `qf=f^w` |
| Phrase fields | `phrase_field_boosts` | nested `phrase` clause | `params.solr.pf` override | `pf` |
| Tie breaker | `tie_breaker` | `tie_breaker` | `params.solr.tie` override | `tie` |
| Min should match | `min_should_match` | `minimum_should_match` | `params.solr.mm` override | `mm` |
| Fuzziness | `fuzziness` | `fuzziness` | (manual via `~` in query parser) | (manual via `~`) |
| Slop | `slop` | `slop` | `params.solr.ps` override | `ps` |
| Boost function | `boost_fn: {field, type, params}` | `function_score` | boosting stage `bq` override | `boost`, `bf` |
| Reranker model | `rerank_model: {id, top_k}` | `rescore.window_size` + LTR | rerank stage `modelId`, `topK` | LTR plugin model |
| Pipeline stage toggle | `stage_enabled: {stage_id: bool}` | (n/a) | per-stage `enabled` param | (n/a) |

**When a concept doesn't exist natively** (e.g., ES `function_score` rendered as Fusion `bq`), the adapter either provides a best-effort translation OR raises `UnsupportedParameter` at render time. The search-space validator catches this before a study runs (rejects the study definition rather than failing trials individually).

**Fusion's `stage_enabled` parameter** is unique to Fusion — it lets a study toggle individual pipeline stages on/off as a categorical parameter, which is a powerful and engine-specific tuning lever.

## Authentication and credentials

Credentials never live in the database. The `clusters.credentials_ref` column is a key into a mounted secrets file; the adapter resolves it via the mounted-secrets helper from `infra_foundation`.

| `auth_kind` | Credential file format | MVP1 status |
|---|---|---|
| `es_apikey` | base64-encoded `id:api_key` string | Active |
| `es_basic` | YAML: `{username, password}` | Active |
| `opensearch_basic` | YAML: `{username, password}` | Active |
| `opensearch_sigv4` | YAML: `{access_key_id, secret_access_key, region, role_arn?}` | Reserved; raises `NotImplementedError` until **MVP3** (AWS managed OpenSearch) |
| `fusion_session` | YAML: `{username, password, session_url}` | Reserved for **MVP3** (Lucidworks Fusion adapter) |
| `fusion_jwt` | YAML: `{jwt_token, refresh_url?}` | Reserved for **MVP3** (Lucidworks Fusion adapter) |
| `solr_basic` | YAML: `{username, password}` | Reserved for **v2+** (Apache Solr adapter) |

## Reserved for later releases

Adapter implementations described here for architectural orientation. Each will get its own implementation file when it ships.

### LucidworksFusionAdapter (MVP3)

Lucidworks Fusion is built on Solr but exposes a different API surface centered on Query Pipelines. Pure-Solr deployments will be supported architecturally (see SolrAdapter notes below) but are deferred to v2+.

- `search_batch` posts to Fusion's query API: `POST /api/apps/{app}/query/{collection}` with the request body holding query text and per-stage parameter overrides (`params.{stageId}.{paramName}`).
- `render` produces a Fusion request body, NOT a raw Solr query. A "template" in Fusion is a query pipeline definition exported as JSON, plus a parameter-binding map.
- `get_schema` queries Fusion's catalog API.
- `explain` uses `params.solr.debugQuery=true` and parses the `debug.explain` block returned through the Fusion gateway.
- **Authentication:** session-based (`POST /api/session`) or JWT.
- **Pipeline export/import:** apply path uses Fusion's `objects-export` and `objects-import` APIs.
- **Signals (v1.5+):** Fusion's signals collections capture user click/view/refinement events. The adapter exposes a `pull_signals` operation for click-derived judgment generation.
- Supports Fusion 5.x.

### SolrAdapter (v2+; architectural reference only)

Pure Apache Solr is supported by the same adapter pattern but is not built before v2 because the early-release user's deployment is Lucidworks Fusion (which arrives at MVP3).

- `search_batch` uses parallel `/select` requests (Solr has no `_msearch` equivalent).
- `render` produces Solr query parameters as a dict; supports `lucene`, `edismax`, `dismax` parsers.
- `explain` uses `debugQuery=true&debug=results`.
- Supports Solr 8.11+ and 9.x; SolrCloud and standalone.

## Cross-references

- Stack choices (httpx async, Pydantic v2 models for the Protocol): [`tech-stack.md`](tech-stack.md)
- `clusters` table backing the registered clusters: [`data-model.md`](data-model.md)
- API conventions for `/clusters/{id}/...` endpoints: [`api-conventions.md`](api-conventions.md)
- Service topology (where the adapter dispatch happens): [`system-overview.md`](system-overview.md)
- MVP1 feature spec: [`infra_adapter_elastic/feature_spec.md`](../02_product/planned_features/infra_adapter_elastic/feature_spec.md)
- MVP1 navigation summary: [`mvp1-overview.md`](mvp1-overview.md)
