# Feature Specification — Index Document Browser

**Date:** 2026-05-27
**Status:** Draft
**Owners:** Eric Starr (Product + Engineering)
**Related docs:**
- [idea.md](idea.md) — origin brief with locked decisions D-1 through D-9
- [pipeline_status.md](pipeline_status.md) — pipeline stage tracker
- [`docs/01_architecture/adapters.md`](../../../01_architecture/adapters.md) — `SearchAdapter` Protocol shape
- [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md) — error envelope, cursor pagination, X-Total-Count
- [`docs/01_architecture/cluster-lifecycle.md`](../../../01_architecture/cluster-lifecycle.md) — the 6 existing cluster endpoints

---

## 1) Purpose

- **Problem:** Studies score against a specific index but operators have no UI path to the documents in that index. They drop to `curl http://localhost:9200/<index>/_search` mid-demo to answer "why did this query regress?" or "what does a sample doc look like?" The friction surfaced during a live walkthrough of `tune-acme-products-rich-boosts`.
- **Outcome:** A read-only document browser, reachable from two independent entry points (cluster detail + study detail), that lets operators see corpus shape, paginate documents, and inspect any single doc's `_source` without leaving the RelyLoop UI. Demos stay coherent; non-engineer stakeholders can follow.
- **Non-goals:** Free-text search across the corpus; "run this study's template against the corpus" playground; mutation of any kind; UBI-index role chips. All deferred per idea D-4 and D-9.

## 2) Current state audit

### Existing implementations

| Surface | File | Today's behavior | Differences from spec assumptions |
|---|---|---|---|
| Cluster detail page | [`ui/src/app/clusters/[id]/page.tsx`](../../../../ui/src/app/clusters/[id]/page.tsx) | Renders `ClusterDetailSummary` + `ClusterActionBar` + `StudiesByClusterTable`. No indices listing. | Confirmed: the "Indices" card is genuinely new content, not a refactor. |
| Cluster targets endpoint | [`backend/app/api/v1/clusters.py:329`](../../../../backend/app/api/v1/clusters.py) `GET /api/v1/clusters/{cluster_id}/targets` | Returns `TargetListResponse(data: list[TargetInfo])` — name + `doc_count`. Used by `feat_create_study_target_autocomplete`. | Reused by Cap A (Indices card). Already filters out system (`.`-prefixed) indices server-side. |
| Cluster schema endpoint | [`backend/app/api/v1/clusters.py:301`](../../../../backend/app/api/v1/clusters.py) `GET /api/v1/clusters/{cluster_id}/schema?target=<name>` | Returns `Schema(name, fields: list[FieldSpec(name, type, analyzer, doc_count)])`. Used only by create-study template validation today. | Reused by Cap B (Index summary). |
| `run_query` endpoint | [`backend/app/api/v1/clusters.py:372`](../../../../backend/app/api/v1/clusters.py) `POST /api/v1/clusters/{cluster_id}/run_query` | Executes arbitrary `query_dsl` + `top_k` + `timeout_s`. **Zero UI consumers today.** | Not used in V1; substrate for deferred `feat_cluster_query_playground` (idea D-4). |
| `LinkedEntitiesRow` | [`ui/src/components/studies/linked-entities-row.tsx`](../../../../ui/src/components/studies/linked-entities-row.tsx) | Renders 4 entries: Cluster / Query set / Judgment list / Template. | Cap 3 extends to 5 entries by appending an `Index` entry. `studies.target` is the data source. |
| `SearchAdapter` Protocol | [`backend/app/adapters/protocol.py`](../../../../backend/app/adapters/protocol.py) | Exposes `health_check / list_targets / get_schema / list_query_parsers / render / search_batch / explain`. **No `get_document` method.** | Spec adds `get_document(target, doc_id) -> Document \| None` (FR-1). |
| `ElasticAdapter.search_batch` | [`backend/app/adapters/elastic.py:559`](../../../../backend/app/adapters/elastic.py) | NDJSON `_msearch` call returning `dict[query_id, list[ScoredHit(doc_id, score, source)]]`. | Reused for the documents list endpoint via a `match_all` query + `search_after` cursor (FR-3). |
| `prettyPrintJinjaJson` | [`ui/src/lib/jinja-json-format.ts:26`](../../../../ui/src/lib/jinja-json-format.ts) | Jinja-aware pretty-printer (PR #282). Sentinelling step is a no-op on pure JSON. | Cap 2 uses plain `JSON.stringify(source, null, 2)` (simpler; no Jinja need). |
| `<DataTable>` primitive | [`ui/src/components/common/data-table.tsx`](../../../../ui/src/components/common/data-table.tsx) | Cursor-stack pagination, opaque cursor (per Story 2.5/2.7). | Reused for Cap 1 (documents list). |
| `/api/v1/studies` list | [`backend/app/api/v1/studies.py:451`](../../../../backend/app/api/v1/studies.py) | Accepts `?cursor=`, `?limit=`, `?since=`, `?status=`, `?cluster_id=`, `?q=`, `?sort=`. **No `?target=` filter.** | FR-5 adds the `?target=` filter so Cap B's "View studies targeting this index" nav card can resolve. |

### Navigation and link impact

The browser is reachable from two new entry points; no existing links change.

| Source file | Current link target | New link target |
|---|---|---|
| [`ui/src/app/clusters/[id]/page.tsx`](../../../../ui/src/app/clusters/[id]/page.tsx) | — | `Indices` card → `/clusters/[id]/indices/[name]` (Cap A) |
| [`ui/src/components/studies/linked-entities-row.tsx`](../../../../ui/src/components/studies/linked-entities-row.tsx) | 4-entry row | 5-entry row — appends `Index` link → `/clusters/[cluster_id]/indices/[target]` (Cap 3) |
| [`ui/src/app/clusters/[id]/indices/[name]/page.tsx`](../../../../ui/src/app/clusters/[id]/indices/[name]/page.tsx) (NEW) | — | `Browse documents →` link to `.../documents`; `View studies targeting this index →` to `/studies?target=<name>` |
| [`ui/src/app/clusters/[id]/indices/[name]/documents/page.tsx`](../../../../ui/src/app/clusters/[id]/indices/[name]/documents/page.tsx) (NEW) | — | Each row → `.../documents/[doc_id]` |

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| [`ui/src/__tests__/components/studies/linked-entities-row.test.tsx`](../../../../ui/src/__tests__/components/studies/linked-entities-row.test.tsx) | Assertions on 4 entries | est. 1-3 | Update to 5 entries; add assertion for `Index` href |
| Any cluster-detail page test (TBD by grep at impl time) | Asserts current card composition | est. 1-2 | Add assertion for new `Indices` card placement |
| `ui/tests/e2e/` Playwright specs | None reference indices browser | 0 | Add new spec `index-document-browser.spec.ts` (real-backend, real seeded corpus) |

### Existing behaviors affected by scope change

- **`SearchAdapter` Protocol surface.** Current: 7 methods. New: 9 methods (`get_document` + `list_documents` added, per D-14 / cycle-2 F4 wording fix). No existing method's signature or semantics changes. Decision needed: **no** — additive only.
- **`/api/v1/studies` query string.** Current: 7 query params. New: 8 params (`?target=` added). Existing behavior unchanged when `?target` is absent. Decision needed: **no** — additive only.

---

## 3) Scope

**Approved deviation from idea D-1** (cycle-3 F9): the spec authorizes adding `list_documents` to the `SearchAdapter` Protocol in addition to `get_document` (`2` new Protocol methods, not `1`). Rationale and blast radius are captured in D-14 / D-23. Conformer audit confirmed only `ElasticAdapter` and `_StubAdapter` need updates.

### In scope

- **Backend**
  - FR-1: `SearchAdapter` — TWO new Protocol methods (`get_document`, `list_documents`) + two new Pydantic models (`Document`, `DocumentPage`)
  - FR-2: `ElasticAdapter` — implementations of both new methods (ES + OpenSearch)
  - FR-3: `GET /api/v1/clusters/{cluster_id}/targets/{target}/documents` — paginated list (routes through `list_documents`)
  - FR-4: `GET /api/v1/clusters/{cluster_id}/targets/{target}/documents/{doc_id}` — single-doc detail (routes through `get_document`)
  - FR-5: `GET /api/v1/studies` — add `?target=<name>` filter
- **Frontend**
  - FR-6: Cluster detail "Indices" card (modified [`/clusters/[id]/page.tsx`](../../../../ui/src/app/clusters/[id]/page.tsx))
  - FR-7: Index summary page (NEW `/clusters/[id]/indices/[name]/page.tsx`)
  - FR-8: Documents list page (NEW `/clusters/[id]/indices/[name]/documents/page.tsx`)
  - FR-9: Document detail page (NEW `/clusters/[id]/indices/[name]/documents/[doc_id]/page.tsx`)
  - FR-10: `LinkedEntitiesRow` 5th entry (modified)

### Out of scope

- Free-text search across the corpus (idea D-4 — deferred to future `feat_cluster_query_playground`)
- "Run this study's template against the corpus" button (idea D-4)
- Confidence-panel improver/regressor → "View returned docs" cross-link (idea D-8 — deferred to D-4)
- Sort by indexed fields other than `_id` (idea D-3 — V1 is `_id` ascending only)
- UBI index role chip on the Indices card (idea D-9 — picked up by `feat_ubi_judgments` in MVP1.5)
- Persisted per-user column visibility / field selection (idea D-5 — `?fields=` query-param narrowing is the V1 surface)
- Schema introspection caching (every page load re-fetches `/schema`)
- Mutations of any kind (PUT/POST/PATCH/DELETE on documents) — read-only by design

### API convention check

Verified against [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md):

- **Endpoint prefix:** `/api/v1/<resource>` for business endpoints. Verified in [`backend/app/api/v1/clusters.py:154-407`](../../../../backend/app/api/v1/clusters.py).
- **Router file:** `backend/app/api/v1/clusters.py` — the documents endpoints extend the existing router; no new router file.
- **HTTP methods:** GET-only for this feature (read-only surface).
- **Error envelope:** `{"detail": {"error_code": "<CODE>", "message": "<human>", "retryable": <bool>}}` per [`api-conventions.md` §"Error envelope"](../../../01_architecture/api-conventions.md). Built via the existing `_err()` helper at [`clusters.py:93`](../../../../backend/app/api/v1/clusters.py).
- **Pagination:** cursor-only — `?cursor=<opaque>&limit=<n>` (default 25, max 100 for documents); `X-Total-Count` header from the engine's `hits.total.value`. Per [`api-conventions.md` §"Pagination"](../../../01_architecture/api-conventions.md).
- **Auth:** N/A — single-tenant, no auth surface in MVP1 (per CLAUDE.md and [`tech-stack.md` §"Canonical release matrix"](../../../01_architecture/tech-stack.md)).

### Phase boundaries

**Single-phase feature.** All in-scope FRs ship in one PR. No `phase2_idea.md` is created from this spec; the deferred surfaces tracked above (D-4 playground, D-9 UBI chip) live in **separate sibling planned-feature folders** that will get their own idea / spec / plan, not phase files under this folder.

Rationale: phase files exist to track work that's a deliberate continuation of *this same feature*. Both deferred surfaces are conceptually distinct features (a query playground and a UBI signal-source taxonomy) that compose with this one but don't extend it.

## 4) Product principles and constraints

- **Engine-specific HTTP only inside `backend/app/adapters/<engine>.py`** (CLAUDE.md Absolute Rule #4). The new endpoints consume the `SearchAdapter` Protocol — never `httpx.AsyncClient` directly in the router or service layer.
- **Read-only.** No mutations; no audit events (audit_log activates at MVP2 for mutations only).
- **No new secrets.** The existing per-cluster credentials (resolved by [`cluster_svc.acquire_adapter`](../../../../backend/app/services/cluster.py)) cover document reads.
- **Single-tenant.** No `tenant_id` scoping; that activates at MVP4.
- **No new migrations.** Read-only over existing ES/OpenSearch indices; no RelyLoop table is touched.
- **Cursor pagination only.** Never `?offset=` / `?from=` / `?page=` — per [`api-conventions.md`](../../../01_architecture/api-conventions.md).
- **No engine-aware UI relabeling in V1.** Frontend uses `Indices` everywhere; engine-aware labels (Fusion → "Collections") arrive if/when MVP3 demands them.

### Anti-patterns

- **Do not** use `from`/`size` deep pagination on the list endpoint — ES caps `from + size` at 10k by default, breaking the IA promise of "browse any corpus." `search_after` over `_id` ascending has no such cap.
- **Do not** call `httpx.AsyncClient` directly from the router or service to fetch documents. Engine HTTP lives only in `ElasticAdapter`.
- **Do not** auto-truncate the full `_source` on the detail endpoint (FR-4). Truncation is list-view-only (FR-3). The detail endpoint serves the complete document.
- **Do not** add a "Run query" or "Search" affordance to the documents list in V1 — it sits on the deferred `run_query` substrate and would force premature design of the query playground.
- **Do not** inline mapping-type chips next to each field key in the doc detail JSON view — clutters the JSON and replicates what Cap B's Schema table shows once.
- **Do not** silently swallow `TARGETS_FORBIDDEN` (403) as `CLUSTER_UNREACHABLE` (503). The two have distinct recovery paths (ACL fix vs cluster down) and the existing adapter classes are wired to distinguish them — preserve the distinction in the new endpoints.
- **Do not** call the new endpoints `.../indices/` on the backend. Backend wire term is `target` (matches `TargetInfo`, `studies.target`, the existing `/clusters/{id}/targets` endpoint). Frontend URL uses `indices` for user-facing clarity — these intentionally diverge.

## 5) Assumptions and dependencies

| Dependency | Why required | Status | Risk if missing |
|---|---|---|---|
| [`SearchAdapter` Protocol](../../../../backend/app/adapters/protocol.py) | Engine boundary the new endpoints route through | Shipped (`infra_adapter_elastic`, 2026-05-10) | None — present |
| [`ElasticAdapter`](../../../../backend/app/adapters/elastic.py) | Concrete implementation for ES + OpenSearch | Shipped (`infra_adapter_elastic`, 2026-05-10) | None — present |
| `studies.target` column | Cap 3's LinkedEntitiesRow 5th entry data source | Shipped (`feat_study_lifecycle`, 2026-05-10) | None — present |
| `<DataTable>` cursor primitive | Cap 1's listing UI | Shipped (`feat_data_table_primitive`, 2026-05-16) | None — present |
| `prettyPrintJinjaJson` precedent | Reference for Cap 2 JSON pretty-print (not actually reused) | Shipped (PR #282, 2026-05-26) | None — present; spec uses plain `JSON.stringify` |
| ES test cluster on `127.0.0.1:9200` | Integration + E2E tests | Available via `make up` | Integration tests skip outside dev — CI service container covers it |
| Seeded `acme-products-rich` index with ≥ 100 docs | E2E pagination coverage | [`scripts/seed_meaningful_demos.py:1040`](../../../../scripts/seed_meaningful_demos.py) seeds the index but the doc count needs verification at impl time | Soft — if too few docs, extend the seed in this PR |

No external services, no new secrets, no third-party API budgets.

## 6) Actors and roles

- **Primary actor:** Relevance engineer (single-tenant, no auth in MVP1).
- **Role model:** N/A — single-tenant install, no auth surface in MVP1–MVP3.
- **Permission boundaries:** Every visitor has full access to every cluster's documents. Engine-side ACL is enforced by the cluster's credentials (e.g., a read-only API key on the operator's ES cluster).

### Authorization

N/A — single-tenant install, no auth surface in MVP1. At MVP4 (per umbrella §18) this surface inherits the same `viewer / runner / tenant_admin / platform_admin` matrix as the other `/clusters/{id}/...` endpoints — likely viewer-readable. Not specified here; ships with MVP4.

### Audit events

N/A — `audit_log` activates at MVP2 for **mutating** endpoints only (per [`data-model.md` §"Forthcoming: audit_log"](../../../01_architecture/data-model.md)). The new endpoints are GET-only, so no audit emission is required at MVP2 either.

---

## 7) Functional requirements

### FR-1: `SearchAdapter` Protocol additions (2 new methods)

- The system **MUST** add two new methods to the `SearchAdapter` Protocol at [`backend/app/adapters/protocol.py`](../../../../backend/app/adapters/protocol.py):
  1. `get_document(self, target: str, doc_id: str, *, request_id: str | None = None) -> Document | None` — single-document fetch by `_id`.
  2. `list_documents(self, target: str, *, search_after: list[Any] | None = None, limit: int = 25, fields: list[str] | None = None, request_id: str | None = None) -> DocumentPage` — paginated `match_all` list with `search_after` cursoring. **Why a new method instead of reusing `search_batch`:** `search_batch` returns `dict[query_id, list[ScoredHit]]` only — it discards `hits.total.value` (verified at [`backend/app/adapters/elastic.py:653-660`](../../../../backend/app/adapters/elastic.py)). FR-3 needs the total for the required `X-Total-Count` header per [`api-conventions.md`](../../../01_architecture/api-conventions.md). A direct `_search` call preserves `hits.total.value`; routing through a method-shaped adapter call keeps Absolute Rule #4 honored.
- Three new Pydantic models accompany the methods (cycle 2 F1 resolution — `last_sort` removed because it can't represent the right hit under `limit+1` overfetch; per-hit `sort` carries the info instead):
  - `Document(doc_id: str = Field(min_length=1), source: dict[str, Any] | None)` — return shape of `get_document`. Mirrors `ScoredHit` minus `score`. F6: `min_length=1` enforces the non-empty invariant at the Pydantic boundary.
  - `AdapterDocumentHit(doc_id: str = Field(min_length=1), source: dict[str, Any] | None, sort: list[Any])` — one hit on the adapter-internal list page. Carries the engine's `hits.hits[i].sort` so the router can compute the cursor from the correct (in-body) hit, not the overfetch hit.
  - `DocumentPage(hits: list[AdapterDocumentHit], total: int)` — return shape of `list_documents`. Adapter returns ALL fetched hits including the `limit+1` overfetch; router slices to the user-facing limit and encodes the cursor from `hits[user_limit - 1].sort` (NOT the overfetch hit).
- Both methods **MUST** be async (per the existing Protocol's `iscoroutinefunction` enforcement in `test_protocol.py`).
- `get_document` **MUST** return `None` when the document does not exist on the target (engine returns 404 / `found: false`).
- Both methods **MUST** raise `TargetNotFoundError` when the target index itself does not exist.
- Both methods **MUST** raise `ClusterUnreachableError` for connection failures / 5xx after the adapter's internal retry budget is exhausted.
- Both methods **MUST** raise `TargetsForbiddenError` when the engine returns 401/403 (preserves the distinction between ACL denial and cluster unreachable, matching the existing `list_targets` pattern at [`elastic.py:404-409`](../../../../backend/app/adapters/elastic.py)).

### FR-2: `ElasticAdapter` implementations

- The system **MUST** implement both `get_document` and `list_documents` in `ElasticAdapter` at [`backend/app/adapters/elastic.py`](../../../../backend/app/adapters/elastic.py).
- **`get_document` implementation:**
  - Call `GET /<target>/_doc/<doc_id>` via the existing `_request` helper (inherits retry + 401/403/5xx translation).
  - A 404 response from the engine with payload `{"found": false}` **MUST** translate to a `None` return value (not an exception).
  - A 404 response from the engine where the **target** does not exist (payload error `type: "index_not_found_exception"`) **MUST** raise `TargetNotFoundError`.
  - Response shape `{"_id": "...", "_source": {...}}` is the success case; `_source` may be absent on engines configured with `_source: false` mappings → return `Document(doc_id=..., source=None)`.
- **`list_documents` implementation:**
  - Call `POST /<target>/_search` via the existing `_request` helper. Body: `{"query": {"match_all": {}}, "sort": [{"_id": "asc"}], "size": <limit>, "track_total_hits": true}` (cycle-3 F2 — `track_total_hits: true` is required because ES caps `hits.total.value` at 10000 by default) plus `"search_after": <search_after>` when present and `"_source": {"includes": <fields>}` when `fields` is non-None.
  - The `target` and `doc_id` path segments **MUST** be URL-encoded before interpolation: `urllib.parse.quote(target, safe="")` and `urllib.parse.quote(doc_id, safe="")` for `get_document` (cycle-3 F3 — without this, IDs containing `/`, `?`, `#`, `%`, or spaces break the engine request). Same encoding applies to `list_documents`'s `target` segment.
  - Translate the engine response: each `hits.hits[i]` → `AdapterDocumentHit(doc_id=hits.hits[i]["_id"], source=hits.hits[i].get("_source"), sort=hits.hits[i]["sort"])`. `hits.total.value` → `DocumentPage.total`. The `sort` per-hit is the engine's native sort-value array — typically `[doc_id]` for the locked `_id:asc` sort, but could include additional tiebreakers in future shapes (forward-compat).
  - 404 with `index_not_found_exception` → `TargetNotFoundError`; 401/403 → `TargetsForbiddenError`; 5xx / connection failures → `ClusterUnreachableError` (matches `list_targets` pattern).
- **Fusion (MVP3) stub:** placeholder methods on the future `LucidworksFusionAdapter` raise `NotImplementedError`. Not a deliverable in this feature; captured as forward-compat note.

### FR-3: `GET /api/v1/clusters/{cluster_id}/targets/{target}/documents` (NEW endpoint)

**Python signature** (cycle-3 F4):

```python
@router.get(
    "/clusters/{cluster_id}/targets/{target}/documents",
    response_model=DocumentListResponse,
    tags=["clusters"],
)
async def list_target_documents(
    cluster_id: str,
    target: str,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    fields: Annotated[str | None, Query(max_length=2048)] = None,
    _strict: Annotated[None, Depends(strict_unknown_query_params({"cursor", "limit", "fields"}))] = None,
) -> DocumentListResponse:
    ...
```


- The endpoint **MUST** accept query params `?cursor=<opaque>` (optional, absent for first page), `?limit=<n>` (default 25, max 100, validated `1 ≤ n ≤ 100` via FastAPI `Query`), and `?fields=<comma_separated>` (optional).
- The endpoint **MUST** enforce the cluster's `target_filter` glob (per F1 finding from GPT-5.5 review). Before delegating to the adapter, the router fetches the cluster row; if `cluster.target_filter` is non-null, the router applies `fnmatch.fnmatchcase(target, cluster.target_filter)` (matches the existing pattern at [`elastic.py:416`](../../../../backend/app/adapters/elastic.py)). When the match fails, the endpoint **MUST** return 404 `TARGET_NOT_FOUND` indistinguishable from a genuinely-missing target (anti-enumeration).
- The endpoint **MUST** route through `SearchAdapter.list_documents` (FR-1) — never `httpx.AsyncClient` directly. The cluster service's existing `acquire_adapter` context manager handles credential injection.
- When `cursor` is present, the endpoint **MUST** decode it to a `search_after` list and pass to `list_documents`.
- When `fields` is present, the endpoint **MUST** parse the comma-separated string per these rules (resolves F7):
  - Split on `,`; trim ASCII whitespace from each segment.
  - Drop empty segments (`?fields=a,,b` → `["a", "b"]`).
  - De-duplicate while preserving order.
  - Accept dotted paths (`?fields=name.keyword,title` → `["name.keyword", "title"]`).
  - Reject wildcards (`?fields=*` or any segment containing `*` → 422 `VALIDATION_ERROR`).
  - If the parsed list is empty after trimming, treat `fields` as absent (no `_source` projection).
- The response shape **MUST** be `DocumentListResponse(data: list[DocumentSummary], next_cursor: str | None, has_more: bool)`. `DocumentSummary` is `(doc_id: str, source: dict[str, Any] | None)`.
- The response **MUST** include `X-Total-Count` header populated from `DocumentPage.total` (engine's `hits.total.value`).
- **`has_more` / `next_cursor` semantics (resolves cycle-1 F4 + cycle-2 F1).** The router requests `list_documents(limit=user_limit + 1)`. The adapter returns `DocumentPage(hits=[AdapterDocumentHit, ...], total=N)` with up to `user_limit + 1` hits, each carrying its own `sort`. If `len(hits) ≤ user_limit`, the page is final: `next_cursor = null`, `has_more = false`. If `len(hits) == user_limit + 1`, the router (a) slices to `hits[:user_limit]` for the response body, (b) encodes the cursor from `hits[user_limit - 1].sort` (NOT `hits[user_limit].sort` — that's the overfetch hit and would skip a doc), and (c) sets `has_more = true`. This guarantees an exact-multiple page-size corpus terminates correctly without an empty final page (AC-15).
- Each `DocumentSummary.source` field value larger than 8 KiB **MUST** be truncated to the string `"<…truncated; full value on detail view…>"`. **Truncation semantics (resolves F10):**
  - Size measure: UTF-8 byte length of `json.dumps(value, ensure_ascii=False)` per top-level `_source` field.
  - Scope: top-level field values only — not recursive into nested objects/arrays. If a top-level field is an object containing 10 sub-fields each at 1 KiB, the parent value's serialized length is ~10 KiB and the parent value is replaced with the sentinel string. Sub-field-level preservation is not a goal.
  - The sentinel string itself is stable: clients may assert on it via the constant `DOCUMENT_FIELD_TRUNCATED` exported from the new module `backend/app/services/documents.py`.
  - Truncation **MUST NOT** be applied to the detail endpoint (FR-4).
  - Implementation **MUST** live in a single server-side helper (`backend/app/services/documents.py::truncate_source_for_list`) — never bypassable from the router because the router calls the helper before returning.
  - **Whole-document cap (cycle-3 F6).** After per-field truncation, if the document's total `json.dumps(source, ensure_ascii=False)` byte length still exceeds 64 KiB (covers the "1000 small fields" attack), the entire `source` field is replaced with `{"__list_view_too_large__": true, "field_count": <N>}` and the stable sentinel constant `DOCUMENT_LIST_VIEW_TOO_LARGE_KEY` is exported alongside `DOCUMENT_FIELD_TRUNCATED`. Operators land on the detail view to see the document.
- The endpoint **rejects** the offset/from/page/since query params with 422 `VALIDATION_ERROR` (cycle-2 F2 resolution — matches the cursor-only stance of D-2 and the engine-pass-through stance of D-13; a silent no-op would mask client bugs). Implementation: a `strict_unknown_query_params` FastAPI dependency that allows-lists `cursor`, `limit`, `fields` and rejects everything else with `_err(422, "VALIDATION_ERROR", f"unknown query param: {name}", False)`.
- Error envelope mappings (envelope shape inherits the global handlers at [`backend/app/api/errors.py:126`](../../../../backend/app/api/errors.py) for FastAPI `RequestValidationError` → 422 `VALIDATION_ERROR` translation; the existing `_err()` helper at [`clusters.py:93`](../../../../backend/app/api/v1/clusters.py) for all router-raised errors):
  - Cluster missing → 404 `CLUSTER_NOT_FOUND`
  - Target missing (genuinely or filtered-out by `target_filter`) → 404 `TARGET_NOT_FOUND`
  - ACL denial → 403 `TARGETS_FORBIDDEN`
  - Cluster down → 503 `CLUSTER_UNREACHABLE` (retryable=true)
  - Invalid cursor → 422 `VALIDATION_ERROR` (retryable=false)
  - Invalid `?fields=` (wildcard) → 422 `VALIDATION_ERROR` (retryable=false)
  - Unknown / disallowed query param (`?since=`, `?offset=`, `?from=`, `?page=`, etc.) → 422 `VALIDATION_ERROR` (retryable=false).

### FR-4: `GET /api/v1/clusters/{cluster_id}/targets/{target}/documents/{doc_id:path}` (NEW endpoint)

**Python signature** (cycle-3 F4):

```python
@router.get(
    "/clusters/{cluster_id}/targets/{target}/documents/{doc_id:path}",
    response_model=Document,
    tags=["clusters"],
)
async def get_target_document(
    cluster_id: str,
    target: str,
    doc_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Document:
    ...
```


- The FastAPI route declaration **MUST** use the `{doc_id:path}` path converter (resolves F2) so document IDs containing `/` (legitimate in ES — e.g., URL-shaped IDs like `https://example.com/p/123`) round-trip correctly. Other URL-significant characters (`%`, `#`, `?`, spaces) **MUST** be URL-encoded by the client (`encodeURIComponent`); the router decodes per FastAPI default.
- The endpoint **MUST** enforce `cluster.target_filter` for `{target}` identically to FR-3 (anti-enumeration via 404 `TARGET_NOT_FOUND`).
- The endpoint **MUST** route through `SearchAdapter.get_document` (FR-1).
- A `None` return value **MUST** translate to HTTP 404 with `error_code: DOCUMENT_NOT_FOUND` (new error code introduced by this feature).
- A success response **MUST** match the Pydantic `Document` shape: `{"doc_id": "...", "source": {...}}` — full `_source` returned, no truncation.
- Error envelope mappings:
  - Cluster missing → 404 `CLUSTER_NOT_FOUND`
  - Target missing (genuinely OR filtered-out by `target_filter`) → 404 `TARGET_NOT_FOUND` (raised by adapter on `index_not_found_exception`, or by router on filter mismatch)
  - Document missing → 404 `DOCUMENT_NOT_FOUND` (NEW)
  - ACL denial → 403 `TARGETS_FORBIDDEN`
  - Cluster down → 503 `CLUSTER_UNREACHABLE` (retryable=true)

### FR-5: `GET /api/v1/studies?target=<name>` filter (EXTENSION) + frontend consumer

**Python signature change** (cycle-3 F4 — concrete diff to the existing handler at [`backend/app/api/v1/studies.py:451`](../../../../backend/app/api/v1/studies.py)):

```python
async def list_studies(
    ...,
    cluster_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    target: Annotated[str | None, Query(min_length=1, max_length=256)] = None,  # NEW
    q: Annotated[str | None, Query(min_length=2, max_length=200)] = None,
    sort: Annotated[StudySortKey | None, Query()] = None,
) -> StudyListResponse:
```

- **Backend:** the studies list endpoint at [`backend/app/api/v1/studies.py:451`](../../../../backend/app/api/v1/studies.py) **MUST** accept a new optional `?target=<name>` query param.
- When present, the result **MUST** be filtered to studies where `studies.target == ?target`.
- The filter **MUST** compose with all existing filters (`status`, `cluster_id`, `since`, `q`, `sort`) via AND.
- The repo functions [`backend/app/db/repo/study.py`](../../../../backend/app/db/repo/study.py) `list_studies` and `count_studies` **MUST** accept and apply the new `target` kwarg.
- The cursor encoding **MUST** remain unchanged — `target` is a non-sort filter.
- **Frontend (resolves F8):** the studies list page at [`ui/src/app/studies/page.tsx`](../../../../ui/src/app/studies/page.tsx) and the API client / TanStack Query hook at [`ui/src/lib/api/studies.ts`](../../../../ui/src/lib/api/studies.ts) **MUST**:
  - Parse `target` from `searchParams` on the studies list page.
  - Thread `target` through the API call (`useStudies({ target, ... })`) and include it in the TanStack Query key so filter changes invalidate cache correctly.
  - Preserve `target` across pagination, sort changes, and status filter changes (active query-string round-tripping).
  - Display an active filter chip "Target: `<name>`" with an `×` to clear, matching the existing `cluster_id` and `status` filter-chip patterns.
- The active filter chip **MUST** carry the same `data-testid` convention used by the other chips (verify exact pattern at impl time; mirror `cluster-filter-chip` etc.).

### FR-6: Cluster detail "Indices" card (Cap A)

- The cluster detail page at [`ui/src/app/clusters/[id]/page.tsx`](../../../../ui/src/app/clusters/[id]/page.tsx) **MUST** add an "Indices" card between `ClusterActionBar` and `StudiesByClusterTable`.
- The card **MUST** fetch `GET /api/v1/clusters/{cluster_id}/targets` via a new TanStack Query hook `useClusterTargets(cluster_id)` at [`ui/src/lib/api/clusters.ts`](../../../../ui/src/lib/api/clusters.ts).
- The card **MUST** render a small table (no cursor — target lists are bounded < 100 items typically): columns `Name` and `Documents` (formatted with thousands separators).
- Each row **MUST** be clickable and navigate to `/clusters/[id]/indices/[name]`.
- Sort by `Name` ascending (client-side; no server-side sort param).
- Empty state: "No indices on this cluster" + link to [`docs/03_runbooks/cluster-registration.md`](../../../03_runbooks/cluster-registration.md).
- 403 `TARGETS_FORBIDDEN` state: "Cluster credentials don't allow listing indices. Register a key with `monitor` privilege." + link to [`docs/04_security/github-token-handling.md`](../../../04_security/github-token-handling.md)'s cluster-credentials section (or the appropriate runbook; verify at impl time).
- 503 `CLUSTER_UNREACHABLE` state: "Cluster is unreachable. Check that the cluster is running and reachable from the API container."

### FR-7: Index summary page (Cap B, NEW)

- New route at `ui/src/app/clusters/[id]/indices/[name]/page.tsx`.
- Page header: index `name`, formatted `doc_count`, engine type chip (from `useCluster(cluster_id).engine_type`).
- Two prominent nav cards rendered with the existing card primitives:
  1. **"Browse documents →"** → `/clusters/[id]/indices/[name]/documents`
  2. **"View studies targeting this index →"** → `/studies?cluster_id=<id>&target=<name>` (cycle-2 F3 — index names can be reused across clusters, so target filter alone is insufficient to mean "studies targeting this index in *this cluster*"; must compose `cluster_id` + `target`). Depends on FR-5.
- Below the nav cards, a Schema table populated from `GET /api/v1/clusters/{cluster_id}/schema?target=<name>` via a new TanStack Query hook `useClusterSchema(cluster_id, target)`:
  - Columns: `Field`, `Type`, `Analyzer`
  - Default sort: field name ascending (client-side)
  - The `doc_count` per-field (when present in `FieldSpec`) hidden behind a column-visibility toggle from the `<DataTable>` primitive
- 404 `TARGET_NOT_FOUND` state: "Index `<name>` does not exist on this cluster" + breadcrumb back to cluster detail.

### FR-8: Documents list page (Cap 1, NEW)

- New route at `ui/src/app/clusters/[id]/indices/[name]/documents/page.tsx`.
- Uses the existing `<DataTable>` primitive with cursor pagination (Story 2.5/2.7 pattern).
- Columns: `_id` (monospace, links to detail), `Preview` (truncated `_source` summary — first 3 fields shown as `key=value` pairs, comma-separated).
- Page size selector: 25 (default), 50, 100.
- Sort: `_id` ascending only (V1 — per idea D-3).
- Empty state: "No documents in this index."
- Error states (403, 503, 404 target): consistent with FR-6 messages.
- Page header above the table: `<name>` (linked back to Cap B summary) + total `X-Total-Count` formatted (e.g., "1,847 documents").

### FR-9: Document detail page (Cap 2, NEW)

- New route at `ui/src/app/clusters/[id]/indices/[name]/documents/[...doc_id]/page.tsx` (Next.js catch-all route per F2 resolution — supports doc IDs containing `/`). The frontend joins the catch-all segments with `/` before passing to the API, and `encodeURIComponent`s on link generation from upstream surfaces.
- Header: breadcrumb `Cluster › Index › <doc_id>` (each segment a link back).
- Body: full `_source` rendered as pretty-printed JSON via `JSON.stringify(source, null, 2)` inside a `<pre>` with code-style font and a copy-to-clipboard button.
- Empty-source case (`source == null`): "This document has `_source: false` configured — only the `_id` is retrievable."
- 404 `DOCUMENT_NOT_FOUND` state: "Document `<doc_id>` does not exist in `<name>`" + breadcrumb back.
- Mapping types are NOT shown on this view (per idea D-7). Operators who need field types open the index summary page (Cap B) via the breadcrumb.

### FR-10: `LinkedEntitiesRow` 5th entry (Cap 3, MODIFIED)

- [`ui/src/components/studies/linked-entities-row.tsx`](../../../../ui/src/components/studies/linked-entities-row.tsx) **MUST** append a 5th `<Entry>` after the existing 4:
  - Label: `Index`
  - Name: `study.target` (no fetch needed — `target` is already on `StudyDetail`)
  - Href: `/clusters/${study.cluster_id}/indices/${study.target}`
  - `testid`: `linked-index`
- No fallback is needed (the `target` field is always present on `studies` — it's a `Mapped[str]` NOT NULL column per [`backend/app/db/models/study.py:56`](../../../../backend/app/db/models/study.py)).

### FR-11: Cursor encoding format

- The opaque `cursor` query param on FR-3 **MUST** be base64-urlsafe-encoded JSON of `visible_hits[user_limit - 1].sort` — the `sort` array from the LAST hit shown to the user (not the overfetch hit). For the locked `_id:asc` sort this is typically `[<doc_id>]`, but the encoding accepts any JSON-serializable list to remain forward-compatible if sort shape ever grows tiebreakers (per cycle-3 F1 reconciliation).
- Encoder/decoder helpers live in a new module `backend/app/api/v1/_documents_cursor.py` (not the existing `_encode_cursor` at [`clusters.py:101`](../../../../backend/app/api/v1/clusters.py), which encodes `(created_at, id)` for a different sort shape).
- Decode failures **MUST** translate to 422 `VALIDATION_ERROR` (matches the existing pattern at [`clusters.py:108-116`](../../../../backend/app/api/v1/clusters.py)).

### FR-12: Convention deviation — `?since=` is intentionally absent

- The documents list endpoint (FR-3) does NOT accept `?since=<iso8601>` despite [`api-conventions.md` §"Filtering by recency"](../../../01_architecture/api-conventions.md) saying "Every list endpoint MUST accept" it.
- Rationale: documents are engine-pass-through (read from ES/OpenSearch over HTTP at request time), not RelyLoop-DB-backed. The convention's `created_at >= since` semantics presume a uniform RelyLoop `created_at` column; documents have no such column (each index's mapping decides whether and how a created/updated timestamp is stored — `@timestamp`, `created_at`, none, etc.).
- A deliberate `D-13` decision in §19 records this exception so future auditors don't flag it as a convention violation.
- The api-conventions doc **MUST** be updated in §15 docs section to note this exception is acceptable for engine-pass-through endpoints.

## 8) API and data contract baseline

### 7.1 Endpoint surface

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `GET` | `/api/v1/clusters/{cluster_id}/targets/{target}/documents` | Paginated `_id` + `_source` list (FR-3) | `CLUSTER_NOT_FOUND`, `TARGET_NOT_FOUND`, `TARGETS_FORBIDDEN`, `CLUSTER_UNREACHABLE`, `VALIDATION_ERROR` |
| `GET` | `/api/v1/clusters/{cluster_id}/targets/{target}/documents/{doc_id}` | Single-doc detail (FR-4) | `CLUSTER_NOT_FOUND`, `TARGET_NOT_FOUND`, `DOCUMENT_NOT_FOUND` (NEW), `TARGETS_FORBIDDEN`, `CLUSTER_UNREACHABLE` |
| `GET` | `/api/v1/studies?target=<name>` (extension) | Filter studies by target index (FR-5) | `VALIDATION_ERROR` (invalid cursor) |

### 7.2 Contract rules

- Error body **MUST** include `error_code` — verified against `_err()` helper at [`clusters.py:93`](../../../../backend/app/api/v1/clusters.py).
- Status codes **MUST** be deterministic per scenario (no 200 with error body).
- Cross-tenant unauthorized access — N/A in MVP1 (single-tenant).
- All new endpoints follow the [`api-conventions.md`](../../../01_architecture/api-conventions.md) error envelope. Cursor pagination, `X-Total-Count` header per the same.

### 7.3 Response examples

**FR-3 success (list — first page, 2 docs returned):**
```json
{
  "data": [
    {
      "doc_id": "prod-001",
      "source": {
        "title": "Apple Watch Series 3",
        "brand": "Apple",
        "price": 199.0
      }
    },
    {
      "doc_id": "prod-002",
      "source": {
        "title": "Apple Watch Series 4",
        "brand": "Apple",
        "price": 299.0
      }
    }
  ],
  "next_cursor": "WyJwcm9kLTAwMiJd",
  "has_more": true
}
```

The `next_cursor` value `WyJwcm9kLTAwMiJd` is `base64url(json.dumps(["prod-002"]))`. Cursor is a JSON list (matching `DocumentPage.last_sort`), NOT an object — F3 resolution.
Response headers include `X-Total-Count: 1847`.

**FR-3 truncation case (single field > 8 KiB):**
```json
{
  "data": [{
    "doc_id": "prod-001",
    "source": {
      "title": "...",
      "description": "<…truncated; full value on detail view…>"
    }
  }],
  "next_cursor": null,
  "has_more": false
}
```

**FR-4 success (detail):**
```json
{
  "doc_id": "prod-001",
  "source": {
    "title": "Apple Watch Series 3",
    "brand": "Apple",
    "price": 199.0,
    "description": "Full text of any length, never truncated on the detail endpoint."
  }
}
```

**Failure examples (apply to FR-3 and FR-4; matches the existing `_err()` envelope):**

404 cluster missing:
```json
{ "detail": { "error_code": "CLUSTER_NOT_FOUND", "message": "cluster 'abc-123' not found", "retryable": false } }
```

404 target missing:
```json
{ "detail": { "error_code": "TARGET_NOT_FOUND", "message": "target 'acme-prodcuts' not found", "retryable": false } }
```

404 document missing (FR-4 only):
```json
{ "detail": { "error_code": "DOCUMENT_NOT_FOUND", "message": "document 'prod-9999' not found in 'acme-products'", "retryable": false } }
```

403 ACL denial:
```json
{ "detail": { "error_code": "TARGETS_FORBIDDEN", "message": "cluster denied listing call (HTTP 403)", "retryable": false } }
```

503 cluster down:
```json
{ "detail": { "error_code": "CLUSTER_UNREACHABLE", "message": "ConnectError: connection refused", "retryable": true } }
```

422 invalid cursor:
```json
{ "detail": { "error_code": "VALIDATION_ERROR", "message": "invalid cursor: ...", "retryable": false } }
```

### 7.4 Enumerated value contracts

V1 introduces no new enums on the backend wire. The only allowlist surface is the `?fields=` query param's accepted values (which are dynamic per index — no fixed allowlist).

| Field | Accepted values (exact) | Backend source of truth | Frontend call site(s) |
|---|---|---|---|
| `?sort` on `/documents` | _omitted in V1_ (server hardcodes `_id:asc`; no client-controllable sort) | N/A — locked literal in router | N/A |
| `?fields` on `/documents` | dynamic per-index (any field present in `_source`); no allowlist | N/A — server forwards to ES `_source` includes | **None in V1** — backend-only knob, no frontend UI (cycle-2 F5: the `<DataTable>` column-visibility primitive doesn't support dynamic schema-derived fields, and inventing a field picker exceeds V1 scope). Operators can pass `?fields=` directly to the API for debug; the UI always renders the default `_source`. |

No enum drift risk in V1. The `<DataTable>` column config for documents will have a top-of-file comment: `// No enum filters in V1 and no dynamic field projection UI — see feat_index_document_browser §7.4 / D-21`.

### 7.5 Error code catalog

| Code | HTTP Status | Meaning |
|---|---|---|
| `DOCUMENT_NOT_FOUND` | 404 | **NEW.** `GET /api/v1/clusters/{cluster_id}/targets/{target}/documents/{doc_id}` called with a `doc_id` that does not exist in the target. `retryable: false`. |
| `CLUSTER_NOT_FOUND` | 404 | EXISTING (reused). Cluster does not exist or is soft-deleted. `retryable: false`. |
| `TARGET_NOT_FOUND` | 404 | EXISTING (reused, raised by `ElasticAdapter` on `index_not_found_exception`). `retryable: false`. |
| `TARGETS_FORBIDDEN` | 403 | EXISTING (reused). Cluster denied the call due to ACL (401/403 on engine side). `retryable: false`. |
| `CLUSTER_UNREACHABLE` | 503 | EXISTING (reused). Cluster connection failure or 5xx. `retryable: true`. |
| `VALIDATION_ERROR` | 422 | EXISTING (reused). Invalid cursor or malformed `?limit=`. `retryable: false`. |

## 9) Data model and state transitions

### New/changed entities

**No database tables added or modified.** This is a read-only feature over existing engine-side indices.

**New Pydantic models** (in [`backend/app/adapters/protocol.py`](../../../../backend/app/adapters/protocol.py)) — canonical shape per cycle-3 F1 reconciliation:

```python
from pydantic import Field

class Document(BaseModel):
    """A single document by ID — return shape of SearchAdapter.get_document."""
    doc_id: str = Field(min_length=1)
    source: dict[str, Any] | None  # None when _source is disabled on the engine

class AdapterDocumentHit(BaseModel):
    """One hit in an adapter list page. Carries the engine's per-hit `sort` so
    the router can encode the cursor from the correct (in-body) hit under
    the `limit + 1` overfetch pattern.
    """
    doc_id: str = Field(min_length=1)
    source: dict[str, Any] | None
    sort: list[Any]  # engine's hits.hits[i].sort — typically [<doc_id>] for the locked _id:asc sort

class DocumentPage(BaseModel):
    """Return shape of SearchAdapter.list_documents."""
    hits: list[AdapterDocumentHit]
    total: int  # engine's hits.total.value — surfaces as X-Total-Count on the router
```

The router slices `hits[:user_limit]` for the response body and encodes the cursor from `hits[user_limit - 1].sort` when `len(hits) == user_limit + 1`. There is **no `last_sort` field** on `DocumentPage` — the per-hit `sort` carries the equivalent information at the right index, avoiding the cycle-2 F1 defect where `last_sort` referred to the overfetch hit under `limit + 1`.

**New Pydantic models** (in [`backend/app/api/v1/schemas.py`](../../../../backend/app/api/v1/schemas.py)):

```python
class DocumentSummary(BaseModel):
    """One row in the paginated documents list."""
    doc_id: str
    source: dict[str, Any] | None

class DocumentListResponse(BaseModel):
    """FR-3 wire shape."""
    data: list[DocumentSummary]
    next_cursor: str | None
    has_more: bool
```

The detail endpoint (FR-4) returns the `Document` model directly as its response body.

### Required invariants

- **`Document.doc_id` is non-empty.** Validation at the Pydantic boundary.
- **`DocumentSummary.source` truncation invariant.** The truncation sentinel `"<…truncated; full value on detail view…>"` is stable text; clients may rely on it to render a "fetch full doc" CTA (no client does in V1, but the stability is contractual).
- **List cursor stability.** A cursor encodes the last hit's `_id`. Re-issuing the same cursor on a corpus with no inserts since the prior page returns the same next page (modulo deletes). On a corpus with concurrent inserts of IDs lexicographically smaller than the cursor, those inserts are NOT visible on subsequent pages (acceptable — see §4 Risks in idea).

### State transitions

N/A — read-only surface.

### Idempotency/replay behavior

N/A — GET endpoints are idempotent by HTTP semantics.

## 10) Security, privacy, and compliance

- **Threats:**
  1. **Operator's cluster credentials leak.** The new endpoints relay cluster credentials only inside the adapter; never to the API client.
  2. **Sensitive PII in `_source`.** Operators may be browsing customer-data indices; the API returns whatever the cluster credentials permit. This is the cluster admin's responsibility — RelyLoop is a read-passthrough.
  3. **Resource exhaustion via large `_source` payloads.** Mitigated by **two-layer truncation** on FR-3 (list view): per-field 8 KiB cap (replaces individual fields with `<…truncated; full value on detail view…>`) AND whole-document 64 KiB cap (replaces entire `source` with `{"__list_view_too_large__": true, "field_count": N}` for docs that survive per-field truncation but still sum > 64 KiB — cycle-3 F6). Detail endpoint (FR-4) returns the full document — operators who request a 50 MB doc get one response of that size; no streaming.
  4. **Cross-cluster ID enumeration.** Not applicable — single-tenant, every operator can already list every cluster.
  5. **`_id` sort compatibility (cycle-3 F5).** Modern Elasticsearch (8.x+) may restrict or warn on direct `_id` sort. The integration test suite at [`tests/integration/test_documents_endpoints.py`](../../../../backend/tests/integration/test_documents_endpoints.py) **MUST** include a real-backend pagination test that proves `sort: [{"_id": "asc"}]` works on the CI ES image. If the test fails at implementation time, the fallback list (in priority order): (a) `sort: [{"_doc": "asc"}]` — insertion order via internal `_doc` field, segment-merge-stable for browse-only use; (b) Point-in-Time (PIT) + `_shard_doc` — opens a PIT, sorts by `_shard_doc`, closes the PIT; requires extending the adapter with PIT lifecycle methods (larger change, defer to a follow-on if `_doc` works). Decision point with explicit fallback list keeps the spec implementable even if the primary strategy fails.
- **Controls:**
  - Adapter-level credential handling unchanged (mounted-secret file pattern per CLAUDE.md Absolute Rule #2).
  - 8 KiB field-truncation on FR-3 enforced server-side.
  - Per-cluster `target_filter` glob already restricts which indices appear in `list_targets()` — the documents endpoints inherit that restriction transparently (a query against a filtered-out target name produces 404 `TARGET_NOT_FOUND`).
- **Secrets:** No new secrets. Per-cluster credentials are resolved by [`cluster_svc.acquire_adapter`](../../../../backend/app/services/cluster.py) (existing pattern).
- **Auditability:** N/A — `audit_log` covers mutations only (MVP2+).
- **Data retention:** N/A — read-only.

## 11) UX flows and edge cases

### Information architecture

The IA was negotiated in the idea (D-6, D-7) and is the load-bearing UX choice.

- **Navigation placement:**
  - **Top-down entry:** Cluster detail page → new "Indices" card → index summary → Browse documents → doc detail.
  - **Bottom-up entry:** Study detail page → `LinkedEntitiesRow` `Index` link → index summary (jumps directly past the cluster step since the cluster is already established).
- **Labeling taxonomy:**
  - `Indices` (card title, UI label) ↔ `targets` (backend wire term) — see anti-pattern in §4 forbidding backend `/indices/` paths.
  - `Documents` (top-down nav card on summary), `Browse documents →` (button text).
  - `View studies targeting this index →` (button text on summary) — depends on FR-5.
  - `Schema` (table heading on summary).
  - On the doc detail page: breadcrumb `<cluster name> › <index name> › <doc_id>`.
- **Content hierarchy:** On cluster detail, the Indices card slots between action bar and studies-by-cluster table — primary "what's here" content above "what's been done with it" content.
- **Progressive disclosure:** Schema table on Cap B uses `<DataTable>`'s column-visibility toggle to hide per-field `doc_count` by default (only present when the engine returns it via the existing `FieldSpec.doc_count` field).
- **Relationship to existing pages:** Cluster detail page **gains** content (no displacement). Study detail page **gains** a `LinkedEntitiesRow` entry (no displacement). Three pages are entirely new.

### Tooltips and contextual help

| Element | Tooltip / help text | Trigger | Placement | Glossary key |
|---|---|---|---|---|
| Cap A "Indices" card title | `An index (Elasticsearch / OpenSearch) is the collection of documents your studies score against. Click a row to inspect the corpus.` | hover on `<InfoTooltip>` next to title | top | NEW key: `cluster.indices_card` — added in this PR to [`ui/src/lib/glossary.ts`](../../../../ui/src/lib/glossary.ts) |
| Cap A `Documents` column header | `Document count as reported by the engine (cat indices). May lag actual count on a heavily-indexing cluster.` | hover on `<InfoTooltip>` | top | NEW: `cluster.target_doc_count` |
| Cap B `Schema` heading | `The field shapes the engine has indexed. Use this to confirm your study's template is referencing the right field names.` | hover | top | NEW: `target.schema` |
| Cap B Schema `Analyzer` column | `The text analyzer applied at index time. Affects how queries against this field are tokenized.` | hover | top | NEW: `target.schema_analyzer` |
| Cap 1 truncation sentinel cell | `Field value exceeded 8 KiB on the list view. Click the row to see the full document.` | hover | top | NEW: `document.truncation_sentinel` |
| Cap 2 `Copy JSON` button | `Copy the document's full _source to your clipboard.` | hover | top | inline — no glossary key (operational action, not domain concept) |
| FR-10 `LinkedEntitiesRow` `Index:` entry | (no tooltip — label is self-explanatory and parallels the existing 4 entries which also have no tooltips) | — | — | — |

Five new glossary keys land in [`ui/src/lib/glossary.ts`](../../../../ui/src/lib/glossary.ts) in this PR. Pattern matches the existing 49-key glossary structure from `feat_contextual_help` PR #122.

### Primary flows

1. **Top-down: explore a cluster's corpus.**
   `/clusters` list → click cluster → cluster detail → Indices card → click `acme-products-rich` → index summary → click `Browse documents →` → paginate → click row → doc detail.

2. **Bottom-up: explain a study's results.**
   `/studies/<id>` → LinkedEntitiesRow `Index: acme-products-rich` link → index summary (skips cluster step) → either `Browse documents →` (corpus inspection) or `View studies targeting this index →` (compare with sibling studies on the same target).

3. **Schema verification on study creation.**
   When an operator is debugging a study that scored 0.0, they jump from `/studies/<id>` to the index summary via the LinkedEntitiesRow link, check the Schema table to confirm the fields their template references exist (e.g., `title.keyword` is present), then either fix the template or open documents to see real values.

### Edge / error flows

- **Empty index:** Cap 1 (Documents list) renders the standard empty-state "No documents in this index." The Indices card still lists the row with `0` documents. Cap B (summary) shows `0 documents` in the header.
- **Index doesn't exist:** Cap B and Cap 1 both surface 404 `TARGET_NOT_FOUND` with a breadcrumb back to cluster detail.
- **Document doesn't exist:** Cap 2 surfaces 404 `DOCUMENT_NOT_FOUND` with a breadcrumb back to the documents list.
- **Cluster ACL denies indices listing (`/targets` returns 403) while per-target schema/doc reads work (cycle-3 F8 partial-permission state):** Cap A (Indices card) surfaces 403 `TARGETS_FORBIDDEN` inline. The bottom-up path (Cap 3 study → index link) lands on Cap B (summary). Cap B **MUST** render in degraded mode:
  - Page header still renders the `name` and engine type; `doc_count` shows as `unknown` (italicized) since the source endpoint is forbidden.
  - The "Browse documents →" nav card remains active (the documents endpoint uses different ACL — engine-level `_search` rather than `/_cat/indices`; may still work).
  - The Schema table is populated from `/schema?target=<name>` which uses a different ACL path (works if the cluster credential has read access to the specific target).
  - If `/schema` ALSO returns 403, the entire page degrades to "Cluster credentials don't allow inspecting this index" with a breadcrumb to the cluster page.
  - A vitest component test covers the partial-permission path: `/targets` 403, `/schema` 200, doc_count rendered as `unknown`.
- **Cluster down:** All endpoints return 503 `CLUSTER_UNREACHABLE`. The Indices card surfaces this inline; the documents list and detail surface it on the page with a "Retry" button (TanStack Query's `refetch`).
- **Stale cursor (mid-browse corpus rebuilt):** Cursor decode succeeds but `search_after` returns 0 hits → the page renders empty with a "Page may be stale" notice and a link back to page 1.
- **Browser tab switch and return:** TanStack Query's default cache (5 min stale) means returning to a previously-viewed documents list re-fetches in the background; no user-visible flash unless the corpus changed materially.

## 12) Given/When/Then acceptance criteria

### AC-1: Cluster detail surfaces the Indices card

- Given a cluster `acme-cluster` exists with 3 indices visible to `list_targets()`
- When the operator navigates to `/clusters/<id>`
- Then the page renders a card titled "Indices" between the action bar and the studies-by-cluster table
- And the card lists 3 rows, each with name + `doc_count` (formatted), sorted by name ascending
- Example: `acme-products-rich (1,847 docs)`, `acme-products (1,847 docs)`, `acme-queries (10 docs)`

### AC-2: Index summary page shows schema + counts + nav cards

- Given `acme-products-rich` exists on `acme-cluster` with 12 indexed fields and 1,847 docs
- When the operator navigates to `/clusters/<id>/indices/acme-products-rich`
- Then the page renders a header `acme-products-rich · 1,847 docs · elasticsearch`
- And renders two nav cards `Browse documents →` and `View studies targeting this index →`
- And renders a Schema table with 12 rows, columns `Field`, `Type`, `Analyzer`, sorted by field name ascending

### AC-3: Documents list paginates with cursor

- Given `acme-products-rich` has 1,847 docs sorted by `_id` ascending
- When the operator visits `/clusters/<id>/indices/acme-products-rich/documents`
- Then the first response from `GET /api/v1/clusters/<id>/targets/acme-products-rich/documents` returns 25 docs, `next_cursor` non-null, `has_more: true`
- And `X-Total-Count: 1847` in headers
- When the operator clicks `Next →`
- Then page 2 returns the next 25 docs ordered by `_id` ascending, with `next_cursor` non-null

### AC-4: Documents list respects `limit` ≤ 100

- Given `acme-products-rich` has 50 docs
- When the operator requests `GET /api/v1/clusters/<id>/targets/acme-products-rich/documents?limit=100`
- Then the response returns all 50 docs in a single page, `next_cursor: null`, `has_more: false`
- When the operator requests `?limit=101`
- Then the response is 422 `VALIDATION_ERROR`

### AC-5: Document detail returns full `_source` with no truncation

- Given doc `prod-001` exists in `acme-products-rich` with a `description` field of 12 KiB
- When the operator requests `GET /api/v1/clusters/<id>/targets/acme-products-rich/documents/prod-001`
- Then the response is 200 with `source.description` containing all 12 KiB verbatim (no truncation)

### AC-6: List view truncates fields > 8 KiB

- Given doc `prod-001` exists in `acme-products-rich` with `description` of 12 KiB and `title` of 16 chars
- When the operator requests `GET /api/v1/clusters/<id>/targets/acme-products-rich/documents`
- Then the row for `prod-001` has `source.description == "<…truncated; full value on detail view…>"`
- And `source.title` is the original 16-char string (under the 8 KiB threshold)

### AC-7: Adapter `get_document` returns `None` on engine 404 (doc missing)

- Given an `ElasticAdapter` connected to a reachable cluster
- And `acme-products-rich` exists on the cluster
- And doc `prod-9999` does NOT exist
- When the test calls `adapter.get_document("acme-products-rich", "prod-9999")`
- Then the return value is `None`
- And no exception is raised

### AC-8: Adapter `get_document` raises `TargetNotFoundError` on missing index

- Given an `ElasticAdapter` connected to a reachable cluster
- And index `nope-not-real` does NOT exist
- When the test calls `adapter.get_document("nope-not-real", "any-id")`
- Then `TargetNotFoundError` is raised

### AC-9: Detail endpoint translates `None` to 404 `DOCUMENT_NOT_FOUND`

- Given a reachable cluster
- And doc `prod-9999` does NOT exist in `acme-products-rich`
- When the operator requests `GET /api/v1/clusters/<id>/targets/acme-products-rich/documents/prod-9999`
- Then the response is HTTP 404 with body `{"detail": {"error_code": "DOCUMENT_NOT_FOUND", "message": "document 'prod-9999' not found in 'acme-products-rich'", "retryable": false}}`

### AC-10: ACL denial surfaces as 403 `TARGETS_FORBIDDEN` on both new endpoints

- Given a cluster configured with a read-only credential that denies `_doc` reads
- When the operator requests `GET /api/v1/clusters/<id>/targets/acme-products-rich/documents` (or `.../documents/<doc_id>`)
- Then the response is HTTP 403 with body `{"detail": {"error_code": "TARGETS_FORBIDDEN", "message": "cluster denied listing call (HTTP 403)", "retryable": false}}`

### AC-11: `LinkedEntitiesRow` has 5 entries

- Given a study with `target == "acme-products-rich"` on cluster `acme-cluster`
- When the operator navigates to `/studies/<id>`
- Then `LinkedEntitiesRow` renders 5 entries: Cluster, Query set, Judgment list, Template, **Index**
- And the `Index` entry's `href` is `/clusters/<cluster_id>/indices/acme-products-rich`
- And clicking the `Index` link navigates to the index summary page (Cap B)

### AC-12: `/studies?target=` filter narrows the studies list

- Given 3 studies exist: 2 with `target="acme-products-rich"`, 1 with `target="acme-products"`
- When the operator requests `GET /api/v1/studies?target=acme-products-rich`
- Then the response `data` contains exactly 2 studies
- And `X-Total-Count: 2`
- When combined with `?cluster_id=<id>` AND `?status=completed`
- Then the result is filtered by all three predicates

### AC-13: Cursor stability across two `Next` clicks

- Given `acme-products-rich` has exactly 60 docs with `_id` values `doc-001` through `doc-060`
- When the operator visits the documents list with `limit=25` and clicks `Next` twice
- Then page 1 returns `doc-001` … `doc-025`, page 2 returns `doc-026` … `doc-050`, page 3 returns `doc-051` … `doc-060` with `next_cursor: null`

### AC-14: target_filter glob anti-enumeration

- Given a cluster registered with `target_filter == "public-*"`
- And the cluster has indices `public-products`, `public-queries`, and `internal-pii`
- When the operator requests `GET /api/v1/clusters/<id>/targets/internal-pii/documents`
- Then the response is HTTP 404 `{"detail": {"error_code": "TARGET_NOT_FOUND", ...}}` — indistinguishable from the response for a genuinely-missing target
- When the operator requests `GET /api/v1/clusters/<id>/targets/public-products/documents`
- Then the response is HTTP 200 with the documents
- Same enforcement applies to the detail endpoint (`/documents/{doc_id}`)

### AC-15: Exact-multiple pagination terminates correctly

- Given `acme-products-rich` has exactly 50 docs
- When the operator requests `GET /api/v1/clusters/<id>/targets/acme-products-rich/documents?limit=25`
- Then page 1 returns 25 docs, `next_cursor` non-null, `has_more: true`
- When the operator passes that cursor to page 2
- Then page 2 returns 25 docs (`doc-026` … `doc-050`), `next_cursor: null`, `has_more: false`
- Page 3 is never requested (the UI hides `Next →` when `has_more: false`)

### AC-16: Doc ID containing `/` round-trips through detail endpoint

- Given doc `https://example.com/p/123` (literal `/` in the ID) exists in `acme-urls-index`
- When the operator requests `GET /api/v1/clusters/<id>/targets/acme-urls-index/documents/https%3A%2F%2Fexample.com%2Fp%2F123` (URL-encoded client side)
- Then the response is HTTP 200 with `doc_id: "https://example.com/p/123"` and the full `_source`
- Verified end-to-end: list view also returns the unencoded ID; frontend `encodeURIComponent` on link generation

### AC-17: Index summary 404 state (cycle-2 F10)

- Given cluster `acme-cluster` exists but `not-a-real-index` does NOT exist on it
- When the operator navigates to `/clusters/<id>/indices/not-a-real-index`
- Then the page renders an empty-state with copy "Index `not-a-real-index` does not exist on this cluster"
- And renders a breadcrumb link `← <cluster_name>` back to cluster detail

### AC-18: Document detail `_source: false` state (cycle-2 F10)

- Given doc `prod-001` exists in `acme-products-rich` but the index is configured `_source: false`
- When the operator navigates to `/clusters/<id>/indices/acme-products-rich/documents/prod-001`
- Then the page renders "This document has `_source: false` configured — only the `_id` is retrievable."
- And renders the doc_id breadcrumb segment as plain text (no copy-JSON button)

### AC-19: Studies-list `target` filter chip is active (cycle-2 F10)

- Given the operator is on `/clusters/<id>/indices/acme-products-rich`
- When they click "View studies targeting this index →"
- Then they navigate to `/studies?cluster_id=<id>&target=acme-products-rich`
- And the studies list page renders an active filter chip labeled "Target: acme-products-rich" with an `×` to clear
- And clicking `×` removes the `target` query param and re-fetches the studies list without that filter (while preserving any active `cluster_id` chip)

### AC-20: 503 retry button refetches (cycle-2 F10)

- Given the documents list endpoint returns 503 `CLUSTER_UNREACHABLE` on the first call
- When the operator clicks the "Retry" button
- Then TanStack Query refetches the list endpoint
- And on a successful second response, the page renders the documents table

## 13) Non-functional requirements

- **Performance:**
  - FR-3 (list) p95 < 500 ms on a 10k-doc corpus with `limit=25` (against a local ES cluster).
  - FR-4 (detail) p95 < 200 ms (single `_doc` lookup).
- **Reliability:** Inherits the adapter's existing single-retry budget for connection failures. No new SLO targets.
- **Operability:**
  - Structured-log event on each call: `documents.list_requested` / `documents.get_requested` with fields `cluster_id, target, cursor_present, limit, status`.
  - Reuse the existing `request_id` propagation pattern (FastAPI middleware → adapter `_request`).
- **Accessibility:**
  - Indices card and Documents table fully keyboard-navigable (uses existing `<DataTable>` patterns).
  - All clickable rows have `role="link"` and ARIA labels.
  - Color contrast for the truncation-sentinel text meets WCAG AA.

## 14) Test strategy requirements

Test coverage is layered to match the AC catalog (AC-1 through AC-20 — cycle-3 F7 corrected the prior stale count). Coverage claims here are what /impl-execute will hold the PR to — if a layer cannot reach an AC, the AC must be downgraded or the layer extended (no silent gaps).

- **Unit (`backend/tests/unit/`):**
  - `adapters/test_elastic_get_document.py` — 6+ tests covering: success path, doc missing (404 → `None`), index missing (`index_not_found_exception` → `TargetNotFoundError`), `_source: false` case, **401/403 → `TargetsForbiddenError`** (resolves F6), 5xx → `ClusterUnreachableError`.
  - `adapters/test_elastic_list_documents.py` — paginated list path: `search_after` round-trip, `limit + 1` overfetch logic, total preservation from `hits.total.value`, `?fields=` projection forwarded to ES `_source.includes`, **401/403 → `TargetsForbiddenError`** (resolves F6), 5xx → `ClusterUnreachableError`.
  - `adapters/test_protocol_documents_methods.py` — Protocol shape assertion: both `get_document` and `list_documents` are present, `runtime_checkable` membership works. **Update [`backend/tests/unit/adapters/test_protocol.py:97`](../../../../backend/tests/unit/adapters/test_protocol.py) to add `"get_document"` and `"list_documents"` to the asserted method-name set, AND update `_StubAdapter` to implement both methods** (resolves F9 / partial F12).
  - `api/v1/test_documents_router_unit.py` — cursor encoding/decoding round-trip with the `[<doc_id>]` list shape; truncation logic at the 8 KiB UTF-8 byte boundary; `?fields=` parsing rules (whitespace trim, dedup, wildcard rejection, empty-segment drop); `target_filter` enforcement via `fnmatch`.
  - `services/test_documents.py` — `truncate_source_for_list` helper at the 8 KiB UTF-8 boundary; top-level-only invariant (nested objects with cumulative > 8 KiB get truncated at the parent value, not recursively).
- **Integration (`backend/tests/integration/`):**
  - `test_documents_endpoints.py` — DB + real ES service-container: seed an index with ≥ 100 docs, paginate end-to-end, fetch by ID, hit doc-missing 404, hit target-missing 404, **hit `target_filter` 404 for filtered-out target** (resolves F1), **hit exact-50-doc pagination terminating correctly** (resolves F4 / AC-15), **hit doc ID containing `/`** (resolves F2 / AC-16), `?fields=` narrowing returns only requested keys, `?fields=*` returns 422. Marked `@pytest.mark.integration`.
  - `test_studies_target_filter.py` — Verify the new `?target=` filter on `/api/v1/studies` (combine with `cluster_id` + `status` filters; cursor stability).
- **Contract (`backend/tests/contract/`):**
  - `test_documents_contract.py` — Response shape assertions against `DocumentListResponse` and `Document`; error envelope shape for each of the 6 error codes (`CLUSTER_NOT_FOUND`, `TARGET_NOT_FOUND`, `DOCUMENT_NOT_FOUND`, `TARGETS_FORBIDDEN`, `CLUSTER_UNREACHABLE`, `VALIDATION_ERROR`); `X-Total-Count` header presence; truncation sentinel preserved verbatim.
  - `test_studies_target_filter_contract.py` — Verify the new `?target=` query param appears in the OpenAPI schema and doesn't change the response shape.
- **E2E (`ui/tests/e2e/`):**
  - `index-document-browser.spec.ts` — Real-backend Playwright spec. NO `page.route()` mocking. Setup via API helper to seed a cluster + index + ≥ 100 docs. Tests:
    - Top-down: cluster detail → Indices card → summary → Browse documents → first 25 rows → click row → detail with full `_source` JSON visible (AC-1, AC-2, AC-3, AC-5).
    - Bottom-up: `/studies/<id>` → LinkedEntitiesRow `Index` link → summary page (AC-11).
    - Studies filter chip: from Cap B "View studies targeting this index →" → studies list page shows active filter chip (AC-12 + F8 frontend behavior).
- **Vitest component (`ui/src/__tests__/`):**
  - `components/clusters/cluster-detail-indices-card.test.tsx` — empty state, happy state, 403 state, 503 state (AC-1 + AC-10).
  - `app/clusters/[id]/indices/[name]/page.test.tsx` — 200 state, 404 `TARGET_NOT_FOUND` state (AC-2, AC-17), partial-permission state where `/targets` is 403 but `/schema` is 200 (cycle-3 F8 — `doc_count` rendered as `unknown`).
  - `app/clusters/[id]/indices/[name]/documents/page.test.tsx` — page rendering with cursor pagination controls; truncation-sentinel rendering (AC-3, AC-6).
  - `app/clusters/[id]/indices/[name]/documents/[...doc_id]/page.test.tsx` — 200 with full JSON, 404 `DOCUMENT_NOT_FOUND`, `source == null` empty state (AC-5, AC-9, AC-16, AC-18).
  - `components/studies/linked-entities-row.test.tsx` — updated assertion: 5 entries, `linked-index` testid present (AC-11).
  - `app/studies/page.test.tsx` (or the existing studies-list component test) — active `Target: <name>` filter chip after navigation from Cap B (AC-19).
  - `app/clusters/[id]/indices/[name]/documents/page.test.tsx` — adds AC-20 retry-button refetch coverage (TanStack Query mocked to return 503 then 200).
- **Coverage gap acknowledgment.** AC-14 (target_filter anti-enumeration) is integration-only — no E2E coverage because Playwright doesn't have a fixture path for registering a cluster with a `target_filter`. Component-level UI tests for 403/503/404 states cover the recovery affordances; the underlying error envelope is contract-tested.

## 15) Documentation update requirements

- [`docs/01_architecture/adapters.md`](../../../01_architecture/adapters.md): document the new `get_document` AND `list_documents` Protocol methods in the methods table; note the Fusion `NotImplementedError` stub plan; note the new `Document` and `DocumentPage` Pydantic models.
- [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md): add `DOCUMENT_NOT_FOUND` to the clusters/documents error-code table; note the `?target=` filter on `/api/v1/studies`; **add a "Convention exceptions" subsection noting that engine-pass-through list endpoints (e.g. documents) are exempt from the `?since=` requirement** (per D-13).
- [`docs/01_architecture/cluster-lifecycle.md`](../../../01_architecture/cluster-lifecycle.md): update the "6 cluster endpoints" framing to "8 cluster endpoints" (adds the two new documents endpoints).
- [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md): add a short subsection on the cluster → indices → documents IA, citing this spec's §11.
- [`docs/03_runbooks/cluster-registration.md`](../../../03_runbooks/cluster-registration.md) (per D-15): extend the "API key auth" section (line 68) with one sentence about the `monitor` privilege requirement for `/_cat/indices` listing.
- No FAQ addition required at ship time. At first sign of "I can't see docs even though my study is running" tickets, an FAQ entry in [`docs/08_guides/`](../../../08_guides/) may be warranted.

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** None. Single-PR ship; read-only surface; no behavioral change to existing endpoints (the `?target=` filter is purely additive).
- **Migration / backfill:** None — no schema change.
- **Operational readiness gates (informed by F12 finding — protocol changes carry broader risk than UI-only additions):**
  - **Protocol conformance.** Update [`_StubAdapter` in test_protocol.py`](../../../../backend/tests/unit/adapters/test_protocol.py) to implement `get_document` and `list_documents`. The asserted method-name set at line 97 grows from 5 to 7. Locally verified before push: `pytest backend/tests/unit/adapters/test_protocol.py` green.
  - **App startup smoke.** `make up` + `/healthz` 200 OK still works (no Protocol member resolution surprises at FastAPI route registration time).
  - **Existing studies list regression.** `GET /api/v1/studies` (no `?target`) returns the same row set as before the PR — locked by an integration test asserting the count equality against a seeded fixture.
  - **Studies-list frontend cache key audit.** The TanStack Query key for `useStudies` includes the new `target` slot; without that, switching the filter chip would not invalidate the cache. Component test confirms.
- **Release gate:** All AC-* pass in CI; all 5 test layers green (unit, integration, contract, vitest component, Playwright E2E); the 5 new glossary keys land in [`ui/src/lib/glossary.ts`](../../../../ui/src/lib/glossary.ts) with the 49-key parity test continuing to pass.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 (Protocol + 2 methods + 2 models) | AC-7, AC-8 | Story 1.1 | `tests/unit/adapters/test_protocol_documents_methods.py` | `adapters.md` |
| FR-2 (ElasticAdapter impls) | AC-3, AC-5, AC-7, AC-8, AC-13 | Story 1.2, 1.3 | `tests/unit/adapters/test_elastic_get_document.py`, `tests/unit/adapters/test_elastic_list_documents.py`, `tests/integration/test_documents_endpoints.py` | `adapters.md` |
| FR-3 (list endpoint) | AC-3, AC-4, AC-6, AC-10, AC-13 | Story 2.1, 2.2 | `tests/contract/test_documents_contract.py`, `tests/integration/test_documents_endpoints.py` | `api-conventions.md`, `cluster-lifecycle.md` |
| FR-4 (detail endpoint) | AC-5, AC-9, AC-10 | Story 2.3 | same as FR-3 | same as FR-3 |
| FR-5 (`?target=` filter) | AC-12 | Story 2.4 | `tests/integration/test_studies_target_filter.py`, `tests/contract/test_studies_contract.py` | `api-conventions.md` |
| FR-6 (Indices card) | AC-1, AC-10 | Story 3.1 | `ui/src/__tests__/components/clusters/cluster-detail-indices-card.test.tsx`, `ui/tests/e2e/index-document-browser.spec.ts` | `ui-architecture.md` |
| FR-7 (Index summary) | AC-2, AC-17, AC-19 | Story 3.2 | `ui/src/__tests__/app/clusters/[id]/indices/[name]/page.test.tsx` (incl. partial-permission state — cycle-3 F8), E2E spec above | `ui-architecture.md` |
| FR-8 (Documents list) | AC-3, AC-4, AC-6, AC-13, AC-20 | Story 3.3 | `ui/src/__tests__/app/clusters/[id]/indices/[name]/documents/page.test.tsx` (incl. AC-20 retry refetch), E2E spec above | `ui-architecture.md` |
| FR-9 (Doc detail) | AC-5, AC-9, AC-16, AC-18 | Story 3.4 | `ui/src/__tests__/app/clusters/[id]/indices/[name]/documents/[...doc_id]/page.test.tsx` (catch-all route per D-17), E2E spec above | `ui-architecture.md` |
| FR-10 (LinkedEntitiesRow) | AC-11 | Story 3.5 | `ui/src/__tests__/components/studies/linked-entities-row.test.tsx`, E2E spec above | — |
| FR-11 (cursor encoding) | AC-3, AC-13 | Story 2.1 | `tests/unit/api/v1/test_documents_cursor.py` | — |
| FR-12 (`?since=` deviation) | — | Story 2.1 | `tests/contract/test_documents_contract.py` (asserts 422 if `?since=` is sent) | `api-conventions.md` |

## 18) Definition of feature done

- [ ] **All AC-1 through AC-20 pass in CI** (cycle-2 F9 — count corrected)
- [ ] **All 5 test layers green**: backend unit, backend integration, backend contract, Vitest component, Playwright E2E (cycle-2 F9)
- [ ] 5 new glossary keys land with parity test passing
- [ ] `adapters.md`, `api-conventions.md`, `cluster-lifecycle.md`, `ui-architecture.md`, `cluster-registration.md` updated (the `monitor` privilege sentence per D-15)
- [ ] No open questions in §19
- [ ] PR ≥ 1 Gemini Code Assist review cycle clean
- [ ] PR final GPT-5.5 review pass clean

## 19) Open questions and decision log

### Open questions

- **OQ-1 — Seed data verification.** The `acme-products-rich` index seeded by [`scripts/seed_meaningful_demos.py:1040`](../../../../scripts/seed_meaningful_demos.py) needs to have ≥ 100 docs for AC-3/AC-13/AC-15 pagination coverage. Verify at impl time; if too few, extend the seed in this PR. Owner: implementer. Due: before Story 3.3.

(All other open questions resolved during GPT-5.5 cycle 1 review — see D-15 below for OQ-2 resolution.)

### Decision log

- **2026-05-27 — D-1 (idea, locked).** Add `get_document(target, doc_id) → Document | None` to `SearchAdapter` Protocol. Rationale: CLAUDE.md Absolute Rule #4 forbids engine HTTP outside `backend/app/adapters/`; faking an ID lookup via `search_batch` + `ids` filter would leak query-DSL construction into the router.
- **2026-05-27 — D-2 (idea, locked).** Cursor pagination via `search_after` over `_id` ascending. Default `limit=25`, max `limit=100`. Matches `<DataTable>` cursor-stack pattern and [`api-conventions.md`](../../../01_architecture/api-conventions.md) ("Pagination").
- **2026-05-27 — D-3 (idea, locked).** V1 sort = `_id` ascending only. "Sort by any indexed keyword field" deferred — needs `get_schema` field-type filtering plus a sort-control UI; not blocking.
- **2026-05-27 — D-4 (idea, deferred).** "Run template against corpus" button + free-text search → future `feat_cluster_query_playground` sibling. Both ride on the existing `POST /clusters/{id}/run_query` endpoint with zero UI consumers today.
- **2026-05-27 — D-5 (idea, locked).** `_source` field display: full by default on Cap 1; `?fields=a,b,c` narrowing knob; 8 KiB per-field truncation on list view; no truncation on detail view; no persisted per-user field-selection state in V1.
- **2026-05-27 — D-6 (idea, locked).** Frontend URL term `indices` (user-facing); backend wire term `target` (matches existing `TargetInfo` / `studies.target` / `/clusters/{id}/targets` endpoint). Engine-aware relabeling (Fusion → "Collections") is a future MVP3 concern.
- **2026-05-27 — D-7 (idea, locked).** Index summary is a real page, not a redirect to `.../documents`. Schema + nav cards live here; absorbs the field-type display that would otherwise clutter Cap 2.
- **2026-05-27 — D-8 (idea, deferred per D-4).** Confidence panel → "View returned docs" cross-link. Needs trial-DSL replay + a playground surface; bundles naturally with D-4.
- **2026-05-27 — D-9 (idea, deferred to MVP1.5).** UBI index `role` chip on Indices card. Picked up by [`feat_ubi_judgments`](../feat_ubi_judgments/idea.md) when it ships; V1 of this feature does not add the `role` field on `TargetInfo`.
- **2026-05-27 — D-10 (spec, locked).** Single-phase delivery. No `phase2_idea.md` produced from this spec; deferred surfaces (D-4 playground, D-9 UBI chip) are tracked in **separate sibling planned-feature folders**, not phase files under this folder.
- **2026-05-27 — D-11 (spec, locked).** `?fields=` narrowing knob has no allowlist — server forwards to ES `_source` includes. Dynamic per-index, no enum drift risk; column-config carries a top-of-file comment confirming intentional absence.
- **2026-05-27 — D-12 (spec, locked).** FR-5 (`?target=` filter on `/api/v1/studies`) is in scope. Resolves idea Open Q "`/studies?target=<name>` filter exists?" by adding ~5 LOC to the studies router + repo functions in the same PR as Cap B.
- **2026-05-27 — D-13 (spec, locked, revised cycle-2 F2).** `?since=<iso8601>` filter is intentionally absent from FR-3. Rationale: documents are engine-pass-through, not RelyLoop-DB-backed; there is no uniform `created_at` column to filter against. **Sending `?since=` (or `?offset=`, `?from=`, `?page=`, or any other non-allowlisted query param) raises 422 `VALIDATION_ERROR`** via a strict-query-param FastAPI dependency. Rationale for explicit rejection over silent no-op: silent acceptance masks client bugs and contradicts the cursor-only stance of D-2; explicit 422 is more discoverable. The api-conventions doc update notes this convention exception applies to engine-pass-through endpoints.
- **2026-05-27 — D-14 (spec, locked — overrides idea's "Cap 1 routes through existing search_batch" claim).** `search_batch` discards `hits.total.value`, which FR-3 requires for `X-Total-Count`. Resolution: add a second new Protocol method `list_documents` that uses `_search` directly. Net cost: 2 Protocol methods + 2 Pydantic models, not 1. The simpler alternative (extending `search_batch` to optionally return `total`) was rejected because `search_batch` is a hot path used by the trial runner, and adding optional return shapes increases its complexity for callers that don't need totals. Concrete blast radius (resolves F9): exactly ONE conforming class needs updating beyond `ElasticAdapter` — [`_StubAdapter` in test_protocol.py`](../../../../backend/tests/unit/adapters/test_protocol.py), plus the asserted method-name set at line 97 grows from 5 names to 7.
- **2026-05-27 — D-15 (spec, locked).** OQ-2 (Forbidden state link target) resolved: the 403 `TARGETS_FORBIDDEN` empty state on Cap A links to [`docs/03_runbooks/cluster-registration.md`](../../../03_runbooks/cluster-registration.md) anchor `#api-key-auth` (line 68 section per current state). This PR **MUST** extend that section with one sentence: "API keys also need the cluster's `monitor` privilege to list indices via `/_cat/indices` — without it, RelyLoop's `/api/v1/clusters/{id}/targets` returns 403 `TARGETS_FORBIDDEN`." This is the §15 docs task added to the existing list.
- **2026-05-27 — D-16 (spec, locked — F1 resolution).** Document endpoints enforce `cluster.target_filter` glob in the router before delegating to the adapter. Anti-enumeration: filtered-out targets return 404 `TARGET_NOT_FOUND` indistinguishable from genuinely-missing targets. Implementation uses `fnmatch.fnmatchcase()` matching the existing pattern in `ElasticAdapter.list_targets`.
- **2026-05-27 — D-17 (spec, locked — F2 resolution).** ES document IDs containing `/` are first-class: backend route uses `{doc_id:path}` converter, frontend uses Next.js catch-all `[...doc_id]`. Other URL-significant characters (`%`, `#`, `?`, spaces) require client-side `encodeURIComponent`; the existing FastAPI / Next.js URL decoding handles the round-trip.
- **2026-05-27 — D-18 (spec, locked — F4 resolution).** Exact-multiple page-size pagination uses `limit + 1` overfetch: the router asks the adapter for `user_limit + 1` hits, returns the first `user_limit` in the body, and sets `has_more` / `next_cursor` from the presence of the extra hit (not encoded in the response). Avoids the empty-final-page defect.
- **2026-05-27 — D-19 (spec, locked — F10 resolution).** 8 KiB truncation: measured as UTF-8 byte length of `json.dumps(value, ensure_ascii=False)` per top-level `_source` field. Non-recursive: nested-object fields > 8 KiB at the parent value's serialized length get replaced wholesale with the sentinel `<…truncated; full value on detail view…>`. Implementation lives in `backend/app/services/documents.py::truncate_source_for_list`; not bypassable from router.
- **2026-05-27 — D-20 (spec, locked — F7 resolution).** `?fields=` parsing: split on comma, trim whitespace, drop empty segments, dedup preserving order, accept dotted paths, reject `*` wildcards with 422 `VALIDATION_ERROR`.
- **2026-05-27 — D-21 (spec, locked — cycle-2 F5 resolution).** `?fields=` is **backend/API-only in V1** — no frontend UI surface. Operators can pass it directly to the API for debug; the UI always renders the default `_source`. Rationale: the `<DataTable>` column-visibility toggle doesn't support dynamic schema-derived columns, and inventing a field picker (with schema introspection + URL round-tripping + pagination preservation) exceeds V1 scope. Future feature can add the UI without breaking the API.
- **2026-05-27 — D-22 (spec, locked — cycle-2 F8 resolution).** `list_studies()` / `count_studies()` repo signature changes add `target: str | None = None` with a default so existing callers stay source-compatible. Implementation **MUST** include a grep audit: `grep -rn "list_studies\|count_studies" backend/` before push to verify no caller is broken by the new kwarg; at least one regression test exercises a no-target call path.
- **2026-05-27 — D-23 (spec, locked — auto mode authorization, cycle-2 F7 resolution).** Per project convention, `--auto` mode authorizes the agent to make architecture-shape decisions on this scope. D-14's override of idea D-1 is authorized; the grep audit for SearchAdapter conformers was performed (see D-14: only `_StubAdapter` exists beyond `ElasticAdapter`). No additional sign-off gate required for this single-developer project.
- **2026-05-27 — D-24 (spec, locked — cycle-3 F2 resolution).** `track_total_hits: true` is included in the `list_documents` `_search` body so `hits.total.value` is exact regardless of corpus size. Without it, ES caps the total at 10000 — which would silently break `X-Total-Count` on corpora >10k docs and contradict the api-conventions promise of "total row count matching the current filter".
- **2026-05-27 — D-25 (spec, locked — cycle-3 F3 resolution).** Adapter-side path encoding via `urllib.parse.quote(segment, safe="")` is mandatory for both `target` and `doc_id` segments. Without it, IDs containing `/`, `?`, `#`, `%`, or spaces produce malformed engine requests. Tested as part of AC-16.
- **2026-05-27 — D-26 (spec, locked — cycle-3 F5 resolution).** Pagination uses `sort: [{"_id": "asc"}]` as primary strategy. If real-backend integration tests fail at impl time on the supported ES image, fallback in priority order: (a) `sort: [{"_doc": "asc"}]`, (b) PIT + `_shard_doc` (larger adapter change; only if `_doc` also fails). Whichever lands ships with an integration test pinning the chosen strategy.
- **2026-05-27 — D-27 (spec, locked — cycle-3 F6 resolution).** Two-layer truncation on list view: (1) per-field 8 KiB cap, (2) whole-document 64 KiB cap with sentinel `{"__list_view_too_large__": true, "field_count": N}`. The constant key is exported alongside `DOCUMENT_FIELD_TRUNCATED`.
- **2026-05-27 — D-28 (spec, locked — cycle-3 F8 resolution).** Cap B (Index summary) supports a degraded partial-permission state when `/targets` returns 403 but `/schema` is accessible. `doc_count` renders as `unknown` (italicized); Browse documents card remains active. Full 403 fallback only when both endpoints fail.
