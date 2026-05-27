# Implementation Plan — Index Document Browser

**Date:** 2026-05-27
**Status:** Complete (PR #285, merged 2026-05-27 as squash `7a5bc42`)
**Primary spec:** [feature_spec.md](feature_spec.md)
**Origin idea:** [idea.md](idea.md)

---

## 0) Planning principles

- Spec traceability first: every story maps to FR IDs from [feature_spec.md §17](feature_spec.md).
- Each epic ends with a hard gate (all endpoints / all UI surfaces / all tests green).
- Tests assert explicit status codes, error envelopes, and DOM elements — no soft assertions.
- Adapter is the only place engine-specific HTTP lives (CLAUDE.md Absolute Rule #4).
- All file paths and function signatures verified against the codebase before this plan was finalized (see ledger at end of plan).

## 1) Scope traceability (FR → epics)

| FR ID | Epic / Story | Notes |
|---|---|---|
| FR-1 (SearchAdapter Protocol additions — `get_document` + `list_documents` + 3 new models) | Epic 1 / Story 1.1 | Adds 2 methods + `Document`, `AdapterDocumentHit`, `DocumentPage` Pydantic models. Updates `_StubAdapter` + `test_protocol.py` method-name set. |
| FR-2 (ElasticAdapter implementations) | Epic 1 / Stories 1.2 (get_document) + 1.3 (list_documents) | Split into two stories because `get_document` is small (~30 LOC) and `list_documents` is larger (search_after + total + per-hit sort propagation). |
| FR-3 (`GET /clusters/{id}/targets/{target}/documents` list endpoint) | Epic 2 / Story 2.2 | Routes through `list_documents`; uses `documents.py` helpers from Story 2.1. |
| FR-4 (`GET .../documents/{doc_id:path}` detail endpoint) | Epic 2 / Story 2.3 | Routes through `get_document`; uses `{doc_id:path}` converter. |
| FR-5 (`?target=` filter on `/studies` + frontend consumer) | Epic 2 / Story 2.4 (backend) + Epic 3 / Story 3.5 (frontend filter chip) | Split because backend filter is a 5-LOC repo change; frontend filter-chip consumer is a UI change. |
| FR-6 (Indices card on cluster detail) | Epic 3 / Story 3.1 | First frontend surface; no new endpoint (reuses `/targets`). |
| FR-7 (Index summary page) | Epic 3 / Story 3.2 | Composes existing `/targets` + `/schema` responses. |
| FR-8 (Documents list page) | Epic 3 / Story 3.3 | Uses `<DataTable>` cursor primitive. |
| FR-9 (Document detail page) | Epic 3 / Story 3.4 | Catch-all `[...doc_id]` route per D-17. |
| FR-10 (LinkedEntitiesRow 5th entry) | Epic 3 / Story 3.5 | Bundled with FR-5 frontend because both edit the same study-side surfaces. |
| FR-11 (Cursor encoding format) | Epic 2 / Story 2.1 | Helper module `backend/app/api/v1/_documents_cursor.py` — pure functions, unit-testable. |
| FR-12 (`?since=` reject + strict-query-param dep) | Epic 2 / Story 2.1 | Helper `strict_unknown_query_params` lives alongside cursor encoder. |

Every FR is covered by at least one story. No phase deferrals from this plan (single-phase per spec D-10).

## 2) Delivery structure

Epic → Story → Tasks → DoD. Three epics, **13 stories** (cycle-3 F3): Stories 1.1–1.3 (3 adapter), 2.1–2.4 (4 backend), 3.1–3.5 (5 frontend), 3.6 (1 E2E).

### Conventions (RelyLoop MVP1)

- Repo functions accept `db: AsyncSession` as the first positional arg; call `await db.flush()` for staging; caller commits.
- Services are async; never raise raw `HTTPException` (raise domain-typed exceptions; routers translate via `_err()`).
- Domain layer is pure — no DB, no async, no I/O.
- Adapters are the only place engine HTTP lives (Absolute Rule #4).
- Pydantic v2; field names `snake_case` matching DB columns.
- New `__init__.py` exports updated via `__all__`.
- Routers use the existing `_err(status, code, message, retryable)` helper at [`clusters.py:93`](../../../../backend/app/api/v1/clusters.py).
- Error envelope: `{"detail": {"error_code": "<CODE>", "message": "<human>", "retryable": <bool>}}` — built by `_err()`.
- E2E tests use real browser interactions via Playwright's `page` object. `page.route()` mocking is **forbidden** per CLAUDE.md.
- Conventional Commits format on every commit; never `--no-verify`.

### AI Agent Execution Protocol

0. Load context: read `architecture.md`, `state.md`, this plan, and the spec before Story 1.1.
1. Read story scope: Outcome + New/Modified files + Endpoints + DoD.
2. Implement backend bottom-up: protocol → adapter → helper → router → schemas.
3. Run backend unit + integration + contract tests after each backend story.
4. Implement frontend top-down: hook → page → component.
5. Run vitest + Playwright after frontend stories.
6. Update docs (architecture.md, ui-architecture.md, api-conventions.md, etc.) in the SAME PR — never later.
7. Migration round-trip — N/A (no migration in this feature).
8. Attach evidence in PR description: commands run, pass/fail, files changed.
9. After Story 3.5 (final), update `state.md` per §4.

---

## Epic 1 — Adapter Protocol & ElasticAdapter implementations

### Story 1.1 — SearchAdapter Protocol: add `get_document`, `list_documents`, and 3 new models

**Outcome:** The `SearchAdapter` Protocol grows from 7 methods (`health_check`, `list_targets`, `get_schema`, `list_query_parsers`, `render`, `search_batch`, `explain`) to 9 methods (+ `get_document`, `list_documents`). Three new Pydantic models (`Document`, `AdapterDocumentHit`, `DocumentPage`) accompany the methods. `_StubAdapter` and the asserted method-name set in `test_protocol.py` are updated so `isinstance(stub, SearchAdapter)` still passes.

**New files**

| File | Purpose |
|---|---|
| (none) | All additions land in existing files. |

**Modified files**

| File | Change |
|---|---|
| [`backend/app/adapters/protocol.py`](../../../../backend/app/adapters/protocol.py) | Add `Document`, `AdapterDocumentHit`, `DocumentPage` Pydantic models. Add `get_document` and `list_documents` Protocol method signatures (both async). |
| [`backend/tests/unit/adapters/test_protocol.py`](../../../../backend/tests/unit/adapters/test_protocol.py) | Update `_StubAdapter` to implement `get_document` and `list_documents` (return shaped stubs). Update the asserted method-name set at line 97 from 5 names to 7 (add `"get_document"`, `"list_documents"`). |

**Endpoints:** none (pure type-system change).

**Key interfaces**

```python
# backend/app/adapters/protocol.py
from pydantic import BaseModel, Field

class Document(BaseModel):
    doc_id: str = Field(min_length=1)
    source: dict[str, Any] | None  # None when _source is disabled

class AdapterDocumentHit(BaseModel):
    doc_id: str = Field(min_length=1)
    source: dict[str, Any] | None
    sort: list[Any]  # engine's hits.hits[i].sort — for router cursor encoding under limit+1 overfetch

class DocumentPage(BaseModel):
    hits: list[AdapterDocumentHit]
    total: int  # engine's hits.total.value (track_total_hits: true required — see Story 1.3)

# Added to the SearchAdapter Protocol class:
async def get_document(
    self, target: str, doc_id: str, *, request_id: str | None = None
) -> Document | None: ...
"""Fetch one document by _id. Returns None on engine 404 (found: false).
Raises TargetNotFoundError on index_not_found_exception; TargetsForbiddenError
on 401/403; ClusterUnreachableError on connection failures / 5xx."""

async def list_documents(
    self,
    target: str,
    *,
    search_after: list[Any] | None = None,
    limit: int = 25,
    fields: list[str] | None = None,
    request_id: str | None = None,
) -> DocumentPage: ...
"""Paginated browse using _search + match_all + search_after over _id:asc + track_total_hits.
Returns DocumentPage with up to `limit` hits (the router asks for `limit + 1` to detect end-of-data).
Same error envelope as get_document."""
```

**Tasks**

1. Add `Document`, `AdapterDocumentHit`, `DocumentPage` models to `protocol.py` (above the `SearchAdapter` class definition, alongside existing `Schema`, `TargetInfo`, `NativeQuery`, `ScoredHit`, `ExplainTree`, `QueryTemplate`).
2. Add the two new method signatures to the `SearchAdapter` Protocol class (after `explain`, preserving the existing method ordering convention).
3. Update `_StubAdapter` in [`test_protocol.py`](../../../../backend/tests/unit/adapters/test_protocol.py): add async `get_document` returning `None` and async `list_documents` returning `DocumentPage(hits=[], total=0)`. Both stub returns are valid shapes for the runtime_checkable assertion.
4. Update the method-name assertion at `test_protocol.py:97` — change the iterated tuple from `("health_check", "list_targets", "get_schema", "search_batch", "explain")` to add `"get_document"` and `"list_documents"`.
5. Run `pytest backend/tests/unit/adapters/test_protocol.py -v` and verify all tests pass.

**Definition of Done (DoD)**

- [ ] `backend/tests/unit/adapters/test_protocol.py` passes (5 → 7 method names asserted, both stub methods present, `isinstance(stub, SearchAdapter)` still True).
- [ ] `mypy --strict` clean on `backend/app/adapters/protocol.py` and `backend/tests/unit/adapters/test_protocol.py`.
- [ ] `Document.doc_id`, `AdapterDocumentHit.doc_id` field validation rejects `""` (add a unit-test assertion in `test_protocol.py`).

---

### Story 1.2 — ElasticAdapter.get_document

**Outcome:** `ElasticAdapter` implements `get_document` by calling `GET /<target_encoded>/_doc/<doc_id_encoded>` via `_request`. Returns `Document(doc_id, source)` on success, `None` on engine `found: false`, raises `TargetNotFoundError` on `index_not_found_exception`, `TargetsForbiddenError` on 401/403, `ClusterUnreachableError` on 5xx / connection failures.

**New files**

| File | Purpose |
|---|---|
| [`backend/tests/unit/adapters/test_elastic_get_document.py`](../../../../backend/tests/unit/adapters/test_elastic_get_document.py) | Unit tests via `httpx.MockTransport` for the 6 paths (success, doc-missing → None, index-missing → TargetNotFoundError, _source:false → source=None, 401/403 → TargetsForbiddenError, 5xx → ClusterUnreachableError). |

**Modified files**

| File | Change |
|---|---|
| [`backend/app/adapters/elastic.py`](../../../../backend/app/adapters/elastic.py) | Add `async def get_document(self, target, doc_id, *, request_id=None) -> Document | None:` method. Insert after `explain` (the last existing method). |

**Endpoints:** none directly; the adapter method is called by the router in Story 2.3.

**Key interfaces**

```python
# backend/app/adapters/elastic.py — inside class ElasticAdapter
async def get_document(
    self,
    target: str,
    doc_id: str,
    *,
    request_id: str | None = None,
) -> Document | None:
    from urllib.parse import quote
    encoded_target = quote(target, safe="")
    encoded_doc_id = quote(doc_id, safe="")
    try:
        resp = await self._request(
            "GET",
            f"/{encoded_target}/_doc/{encoded_doc_id}",
            request_id=request_id,
            translate_errors=False,
        )
    except httpx.HTTPError as exc:
        raise ClusterUnreachableError(str(exc)) from exc
    if resp.status_code in (401, 403):
        raise TargetsForbiddenError(
            f"cluster denied document fetch (HTTP {resp.status_code} from /_doc)"
        )
    if resp.status_code == 404:
        payload = resp.json()
        if isinstance(payload, dict) and payload.get("error", {}).get("type") == "index_not_found_exception":
            raise TargetNotFoundError(target)
        # found: false → return None
        return None
    if resp.status_code >= 400:
        raise ClusterUnreachableError(f"HTTP {resp.status_code} from /_doc")
    payload = resp.json()
    return Document(doc_id=payload["_id"], source=payload.get("_source"))
```

**Tasks**

1. Add the `get_document` method to `ElasticAdapter`. Place it after `explain` to preserve the existing method ordering convention (the Protocol's order: `health_check / list_targets / get_schema / list_query_parsers / render / search_batch / explain / get_document / list_documents`).
2. Write 6 unit tests in `test_elastic_get_document.py` using `httpx.MockTransport` (mirror the pattern at [`test_elastic_msearch.py`](../../../../backend/tests/unit/adapters/test_elastic_msearch.py)).
3. Run `pytest backend/tests/unit/adapters/test_elastic_get_document.py -v`.

**Definition of Done**

- [ ] All 6 unit tests pass: success, found:false → None, index_not_found_exception → TargetNotFoundError, _source absent → source=None, 401/403 → TargetsForbiddenError, 5xx → ClusterUnreachableError.
- [ ] One additional unit test asserts URL encoding: `doc_id="a/b%c"` → request path includes `%2Fb%25c`.
- [ ] mypy --strict clean.

---

### Story 1.3 — ElasticAdapter.list_documents

**Outcome:** `ElasticAdapter` implements `list_documents` by calling `POST /<target_encoded>/_search` with `{"query": {"match_all": {}}, "sort": [{"_id": "asc"}], "size": <limit>, "track_total_hits": true}` (plus `search_after` and `_source.includes` when provided). Returns `DocumentPage(hits: list[AdapterDocumentHit], total: int)`. Errors mirror Story 1.2's mapping.

**New files**

| File | Purpose |
|---|---|
| [`backend/tests/unit/adapters/test_elastic_list_documents.py`](../../../../backend/tests/unit/adapters/test_elastic_list_documents.py) | Unit tests: success with N hits, search_after round-trip, `track_total_hits: true` present in request body, `_source.includes` populated when fields passed, 401/403 → TargetsForbiddenError, 404 index_not_found → TargetNotFoundError, 5xx → ClusterUnreachableError. |

**Modified files**

| File | Change |
|---|---|
| [`backend/app/adapters/elastic.py`](../../../../backend/app/adapters/elastic.py) | Add `async def list_documents(...)` method after `get_document`. |

**Key interfaces**

```python
# backend/app/adapters/elastic.py — inside class ElasticAdapter
async def list_documents(
    self,
    target: str,
    *,
    search_after: list[Any] | None = None,
    limit: int = 25,
    fields: list[str] | None = None,
    request_id: str | None = None,
) -> DocumentPage:
    from urllib.parse import quote
    encoded_target = quote(target, safe="")
    body: dict[str, Any] = {
        "query": {"match_all": {}},
        "sort": [{"_id": "asc"}],
        "size": limit,
        "track_total_hits": True,
    }
    if search_after is not None:
        body["search_after"] = search_after
    if fields is not None:
        body["_source"] = {"includes": fields}
    try:
        resp = await self._request(
            "POST",
            f"/{encoded_target}/_search",
            json=body,
            request_id=request_id,
            translate_errors=False,
        )
    except httpx.HTTPError as exc:
        raise ClusterUnreachableError(str(exc)) from exc
    if resp.status_code in (401, 403):
        raise TargetsForbiddenError(f"cluster denied _search (HTTP {resp.status_code})")
    if resp.status_code == 404:
        payload = resp.json()
        if isinstance(payload, dict) and payload.get("error", {}).get("type") == "index_not_found_exception":
            raise TargetNotFoundError(target)
        raise ClusterUnreachableError(f"HTTP 404 from /_search (unexpected — not index_not_found_exception)")
    if resp.status_code >= 400:
        raise ClusterUnreachableError(f"HTTP {resp.status_code} from /_search")
    payload = resp.json()
    hits_raw = payload.get("hits", {}).get("hits", [])
    total = int(payload.get("hits", {}).get("total", {}).get("value", 0))
    hits = [
        AdapterDocumentHit(
            doc_id=h["_id"],
            source=h.get("_source"),
            sort=h["sort"],  # cycle-2 F10 — fail loud (KeyError) if engine omits sort; trusts ES contract under sort: [...]
        )
        for h in hits_raw
    ]
    return DocumentPage(hits=hits, total=total)
```

Cycle-2 F7 reference: `translate_errors=False` semantics match the existing pattern at [`elastic.py:359-409`](../../../../backend/app/adapters/elastic.py) for `list_targets`: response is returned with its raw status_code; the caller does its own 401/403/4xx/5xx mapping. Connection failures still re-raise from `_request` after the internal retry.

**Tasks**

1. Add `list_documents` to `ElasticAdapter` after `get_document`.
2. Write unit tests in `test_elastic_list_documents.py`:
   - Happy path with 3 hits (assert `hits` list shape + `total` extraction + per-hit `sort` extraction).
   - Request body contains `"track_total_hits": true` (assert via mock transport request capture).
   - `search_after=["doc-002"]` → body contains `"search_after": ["doc-002"]`.
   - `fields=["title", "brand"]` → body contains `"_source": {"includes": ["title", "brand"]}`.
   - 401 → `TargetsForbiddenError`.
   - 404 `index_not_found_exception` → `TargetNotFoundError`.
   - 503 → `ClusterUnreachableError`.
3. Run `pytest backend/tests/unit/adapters/test_elastic_list_documents.py -v`.

**Definition of Done**

- [ ] All 7+ unit tests pass.
- [ ] `track_total_hits: true` asserted in request body (per spec D-24).
- [ ] URL encoding asserted: `target="my/index"` → path is `/my%2Findex/_search`.
- [ ] mypy --strict clean.

---

### Epic 1 Gate

- [ ] `SearchAdapter` Protocol has 9 methods (verified by `test_protocol.py` count assertion).
- [ ] `ElasticAdapter` implements both new methods; `isinstance(ElasticAdapter(...), SearchAdapter)` is True.
- [ ] All unit tests across Stories 1.1–1.3 pass locally.

---

## Epic 2 — Backend endpoints

### Story 2.1 — Documents helper module (cursor, truncation, target_filter, strict-query-params)

**Outcome:** Four pure-function helpers land in a single module so Stories 2.2 and 2.3 can compose them without duplication. Each helper is unit-testable in isolation.

**New files**

| File | Purpose |
|---|---|
| [`backend/app/api/v1/_errors.py`](../../../../backend/app/api/v1/_errors.py) | **NEW** shared module hosting `_err(status_code, code, message, retryable) -> HTTPException`. Resolves the F6 circular-import risk: helpers in this story import from here; `clusters.py` switches its existing local `_err` to a re-export from this module. |
| [`backend/app/api/v1/_documents_cursor.py`](../../../../backend/app/api/v1/_documents_cursor.py) | `encode_documents_cursor(sort: list[Any]) -> str` and `decode_documents_cursor(raw: str) -> list[Any]` — base64-urlsafe JSON of the sort array. Decode raises `HTTPException` built via the shared `_err` helper on malformed input. **Decode MUST validate the parsed value is a `list`** (cycle-2 F9 — a syntactically valid cursor encoding `{}` or a string would otherwise pass through to ES as `search_after` and produce engine errors). |
| [`backend/app/api/v1/_documents_fields.py`](../../../../backend/app/api/v1/_documents_fields.py) | `parse_fields_csv(raw: str | None) -> list[str] | None` (cycle-2 F2: dedicated module, not inline in `clusters.py`). Per spec FR-3: split on `,`, trim whitespace, drop empty segments, dedup preserving order, accept dotted paths, reject `*` wildcards with 422, return `None` when empty after trimming (treats `?fields=` and `?fields=,,,` as absent). |
| [`backend/app/services/documents.py`](../../../../backend/app/services/documents.py) | `truncate_source_for_list(source, *, per_field_cap_bytes=8192, total_cap_bytes=65536) -> dict[str, Any] \| None`. Module-level constants `DOCUMENT_FIELD_TRUNCATED: str` and `DOCUMENT_LIST_VIEW_TOO_LARGE_KEY: str` exported. |
| [`backend/app/api/v1/_strict_query_params.py`](../../../../backend/app/api/v1/_strict_query_params.py) | `strict_unknown_query_params(allowed: set[str]) -> Callable` — FastAPI dependency factory that raises `_err(422, "VALIDATION_ERROR", f"unknown query param: {name}", False)` for any request param not in the allowed set. |
| [`backend/app/services/_target_filter.py`](../../../../backend/app/services/_target_filter.py) | `check_target_visible(cluster, target) -> bool` — uses `fnmatch.fnmatchcase` to match the cluster's `target_filter` glob (None → always True; matching pattern → True; non-matching → False). |
| [`backend/tests/unit/api/v1/test_documents_cursor.py`](../../../../backend/tests/unit/api/v1/test_documents_cursor.py) | Round-trip encode → decode, malformed input → 422, empty list, list with mixed types (str, int, None). |
| [`backend/tests/unit/services/test_documents_truncation.py`](../../../../backend/tests/unit/services/test_documents_truncation.py) | Per-field cap, whole-doc cap, multibyte chars, nested-object top-level value over cap, `None` source → `None` output. |
| [`backend/tests/unit/services/test_target_filter.py`](../../../../backend/tests/unit/services/test_target_filter.py) | Glob match, glob no-match, None filter → always True, anti-enumeration cases. |
| [`backend/tests/unit/api/v1/test_strict_query_params.py`](../../../../backend/tests/unit/api/v1/test_strict_query_params.py) | Allowed param passes; disallowed param raises 422 with correct envelope. |
| [`backend/tests/unit/api/v1/test_documents_fields.py`](../../../../backend/tests/unit/api/v1/test_documents_fields.py) | `parse_fields_csv`: whitespace trim (`" a , b "` → `["a", "b"]`), dedup preserving order (`"a,b,a"` → `["a", "b"]`), dotted paths (`"title.keyword"` → `["title.keyword"]`), wildcard rejection (`"*"` and `"title*"` → 422), empty-after-trim → `None` (`""`, `",,,"`). |

**Modified files**

| File | Change |
|---|---|
| [`backend/app/api/v1/clusters.py`](../../../../backend/app/api/v1/clusters.py) | Replace the local `_err()` function at line 93 with a re-export: `from backend.app.api.v1._errors import _err`. Existing call sites unchanged. |

**Key interfaces**

```python
# backend/app/api/v1/_documents_cursor.py
def encode_documents_cursor(sort: list[Any]) -> str: ...
def decode_documents_cursor(raw: str) -> list[Any]: ...  # raises HTTPException(422, ...) on parse error

# backend/app/services/documents.py
DOCUMENT_FIELD_TRUNCATED: str = "<…truncated; full value on detail view…>"
DOCUMENT_LIST_VIEW_TOO_LARGE_KEY: str = "__list_view_too_large__"

def truncate_source_for_list(
    source: dict[str, Any] | None,
    *,
    per_field_cap_bytes: int = 8192,
    total_cap_bytes: int = 65536,
) -> dict[str, Any] | None:
    """Apply two-layer truncation per spec D-27. UTF-8 byte length of json.dumps(value, ensure_ascii=False)."""

# backend/app/api/v1/_strict_query_params.py
from collections.abc import Callable
from fastapi import Request
def strict_unknown_query_params(allowed: set[str]) -> Callable[[Request], None]: ...

# backend/app/services/_target_filter.py
from backend.app.db.models import Cluster
def check_target_visible(cluster: Cluster, target: str) -> bool: ...
```

**Tasks**

1. Create `_errors.py` with the shared `_err` function (F6 resolution). Update `clusters.py` to re-export.
2. Implement `_documents_cursor.py`: encode via `base64.urlsafe_b64encode(json.dumps(sort).encode())`; decode reverses (catch `binascii.Error`, `json.JSONDecodeError`, etc. → `_err(422, ...)` from `_errors.py`). After JSON-parse, `if not isinstance(value, list): raise _err(422, "VALIDATION_ERROR", ...)` (cycle-2 F9).
3. Implement `documents.py::truncate_source_for_list`:
   - If `source is None`, return `None`.
   - For each top-level field, compute `len(json.dumps(value, ensure_ascii=False).encode("utf-8"))`. If > `per_field_cap_bytes`, replace with `DOCUMENT_FIELD_TRUNCATED`.
   - After per-field pass, compute total `json.dumps(result, ensure_ascii=False).encode("utf-8")` length. If > `total_cap_bytes`, return `{DOCUMENT_LIST_VIEW_TOO_LARGE_KEY: True, "field_count": len(source)}`.
4. Implement `_strict_query_params.py`: FastAPI dependency that compares `request.query_params.keys()` to `allowed`. Disallowed → raise via the shared `_err` import.
5. Implement `_target_filter.py`: `if cluster.target_filter is None: return True; return fnmatch.fnmatchcase(target, cluster.target_filter)`.
6. Implement `parse_fields_csv(raw: str | None) -> list[str] | None` in **`backend/app/api/v1/_documents_fields.py`** (cycle-2 F2 — dedicated module, not inline in `clusters.py`). Behavior per spec FR-3:
   - Split on `,`; trim ASCII whitespace from each segment.
   - Drop empty segments.
   - De-duplicate preserving order.
   - Accept dotted paths.
   - Any segment containing `*` → raise `_err(422, "VALIDATION_ERROR", ...)`.
   - If list is empty after trimming, return `None` (treats `?fields=` and `?fields=,,,` as absent).
7. Write the 5 corresponding unit test files. Cover happy path + at least 2 edge cases each. For `parse_fields_csv` specifically: trim/dedup/dotted-path/wildcard-reject/empty-after-trim per cycle-1 F1 / cycle-2 F2.

**Definition of Done**

- [ ] All 4 helper modules implemented; each has unit tests at 100% branch coverage.
- [ ] `pytest backend/tests/unit/api/v1/test_documents_cursor.py backend/tests/unit/services/test_documents_truncation.py backend/tests/unit/services/test_target_filter.py backend/tests/unit/api/v1/test_strict_query_params.py -v` all green.
- [ ] mypy --strict clean.
- [ ] Constants `DOCUMENT_FIELD_TRUNCATED` and `DOCUMENT_LIST_VIEW_TOO_LARGE_KEY` exported from `backend/app/services/documents.py` (verifiable via `from backend.app.services.documents import DOCUMENT_FIELD_TRUNCATED`).

---

### Story 2.2 — `GET /api/v1/clusters/{cluster_id}/targets/{target}/documents` (list endpoint)

**Outcome:** New endpoint serves paginated `_id` + truncated `_source` list. Routes through `SearchAdapter.list_documents` with `limit + 1` overfetch for exact-multiple-page-size correctness. Enforces `cluster.target_filter` via `check_target_visible`. Rejects unknown query params (`?since=`, `?offset=`, etc.) with 422. Returns `DocumentListResponse` + `X-Total-Count` header.

**New files**

| File | Purpose |
|---|---|
| [`backend/tests/integration/test_documents_endpoints.py`](../../../../backend/tests/integration/test_documents_endpoints.py) | Real-ES integration tests: seed 100+ docs, paginate full corpus, hit `target_filter` 404, hit exact-50-doc terminating page, hit `_source: false` index, hit doc-id-with-slash. Marked `@pytest.mark.integration`. |
| [`backend/tests/contract/test_documents_contract.py`](../../../../backend/tests/contract/test_documents_contract.py) | Response shape assertions for `DocumentListResponse` and all 6 error codes; `X-Total-Count` header presence; truncation sentinel preserved verbatim; strict-query-param rejection of `?since=`. |

**Modified files**

| File | Change |
|---|---|
| [`backend/app/api/v1/clusters.py`](../../../../backend/app/api/v1/clusters.py) | Add `@router.get("/clusters/{cluster_id}/targets/{target}/documents", ...)` handler. Import the new helpers. |
| [`backend/app/api/v1/schemas.py`](../../../../backend/app/api/v1/schemas.py) | Add `DocumentSummary(BaseModel)` and `DocumentListResponse(BaseModel)`. |

**Endpoints**

| Method | Path | Query params | Success response | Error codes |
|---|---|---|---|---|
| `GET` | `/api/v1/clusters/{cluster_id}/targets/{target}/documents` | `?cursor=<opaque>&limit=<1..100, default 25>&fields=<csv>` (other params rejected) | `200` `DocumentListResponse(data: list[DocumentSummary], next_cursor: str \| None, has_more: bool)` + `X-Total-Count: <int>` header | `CLUSTER_NOT_FOUND` (404), `TARGET_NOT_FOUND` (404), `TARGETS_FORBIDDEN` (403), `CLUSTER_UNREACHABLE` (503), `VALIDATION_ERROR` (422) |

**Key interfaces**

```python
# backend/app/api/v1/clusters.py

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
    _strict: Annotated[
        None,
        Depends(strict_unknown_query_params({"cursor", "limit", "fields"})),
    ] = None,
) -> DocumentListResponse:
    cluster = await repo.get_cluster(db, cluster_id)
    if cluster is None:
        raise _err(404, "CLUSTER_NOT_FOUND", f"cluster {cluster_id!r} not found", False)
    if not check_target_visible(cluster, target):
        raise _err(404, "TARGET_NOT_FOUND", f"target {target!r} not found", False)

    parsed_fields = _parse_fields_csv(fields) if fields else None  # rejects '*' with 422
    search_after = decode_documents_cursor(cursor) if cursor else None
    user_limit = limit
    # Request ID propagation: the structlog context (set by FastAPI middleware) auto-attaches
    # request_id to log records. Existing routers (e.g. list_targets at clusters.py:359) do NOT
    # pass request_id to adapter methods — match that pattern. Cycle-3 F4 resolution.

    try:
        async with cluster_svc.acquire_adapter(cluster) as adapter:
            page = await adapter.list_documents(
                target,
                search_after=search_after,
                limit=user_limit + 1,  # overfetch one for has_more detection
                fields=parsed_fields,
            )
    except TargetNotFoundError as exc:
        raise _err(404, "TARGET_NOT_FOUND", f"target {exc.target!r} not found", False) from exc
    except TargetsForbiddenError as exc:
        raise _err(403, "TARGETS_FORBIDDEN", str(exc), False) from exc
    except (ClusterUnreachable, ClusterUnreachableError) as exc:
        raise _err(503, "CLUSTER_UNREACHABLE", str(exc), True) from exc

    visible_hits = page.hits[:user_limit]
    has_more = len(page.hits) > user_limit
    next_cursor = (
        encode_documents_cursor(visible_hits[-1].sort)
        if has_more and visible_hits
        else None
    )

    response.headers["X-Total-Count"] = str(page.total)
    log.info(
        "documents.list_requested",
        cluster_id=cluster_id,
        target=target,
        cursor_present=cursor is not None,
        limit=user_limit,
        status="ok",  # cycle-3 F6 — match spec §13 fields exactly
    )
    return DocumentListResponse(
        data=[
            DocumentSummary(
                doc_id=h.doc_id,
                source=truncate_source_for_list(h.source),
            )
            for h in visible_hits
        ],
        next_cursor=next_cursor,
        has_more=has_more,
    )
```

The same `request_id` propagation + `documents.get_requested` structured-log event applies to FR-4 (Story 2.3). Per spec §13 NFRs.

**Pydantic schemas**

```python
# backend/app/api/v1/schemas.py
class DocumentSummary(BaseModel):
    doc_id: str = Field(min_length=1)
    source: dict[str, Any] | None

class DocumentListResponse(BaseModel):
    data: list[DocumentSummary]
    next_cursor: str | None
    has_more: bool
```

**Tasks**

1. Add `DocumentSummary` and `DocumentListResponse` to `schemas.py`.
2. Import `parse_fields_csv` from `backend/app/api/v1/_documents_fields.py` (created in Story 2.1 — cycle-2 F2 single-source resolution). Do NOT define a second local parser.
3. Add the route handler in `clusters.py`, inserting after the existing `run_query` handler.
4. Update [`backend/app/api/v1/clusters.py`](../../../../backend/app/api/v1/clusters.py)'s docstring header to list the new endpoint.
5. Write contract tests for: response shape, all 6 error codes (assert on `error_code` + status only; message text is illustrative per api-conventions.md "`error_code` is the contract — `message` is for human display, can change freely" — F4 resolution), X-Total-Count header, truncation sentinel preserved, `limit=101` → 422 `VALIDATION_ERROR` (F2 resolution).
6. Write integration tests against the running ES test container (mark `@pytest.mark.integration`):
   - Happy path with 100+ docs paginate end-to-end.
   - Filtered-out target via `cluster.target_filter` → 404 `TARGET_NOT_FOUND`.
   - Exact-50-doc corpus with `limit=25` terminates correctly on page 2 (`has_more: false`).
   - `?fields=title,brand` → only those fields appear in returned `source`.
   - `?fields=*` → 422.
   - `?since=2024-01-01` → 422.
7. Run `make test-unit && make test-contract && pytest -m integration backend/tests/integration/test_documents_endpoints.py`.

**Definition of Done**

- [ ] Endpoint live at `/api/v1/clusters/{cluster_id}/targets/{target}/documents` and visible in `/docs` OpenAPI page.
- [ ] 5 error codes covered by Story 2.2's contract tests with correct envelope shape: `CLUSTER_NOT_FOUND`, `TARGET_NOT_FOUND`, `TARGETS_FORBIDDEN`, `CLUSTER_UNREACHABLE`, `VALIDATION_ERROR`. (`DOCUMENT_NOT_FOUND` is added by Story 2.3 — see F1 cycle-2 split.)
- [ ] X-Total-Count header present on 200 responses (asserted in contract test).
- [ ] Exact-multiple pagination test (AC-15) green.
- [ ] target_filter anti-enumeration test (AC-14) green.
- [ ] Truncation behavior verified in contract test using a doc with a 10 KiB string field.

---

### Story 2.3 — `GET .../documents/{doc_id:path}` (detail endpoint)

**Outcome:** New endpoint fetches a single document by `_id`. Uses FastAPI's `{doc_id:path}` converter to round-trip IDs containing `/` (D-17). Routes through `SearchAdapter.get_document`. Enforces `cluster.target_filter`.

**New files:** none (test files extend Story 2.2's `test_documents_endpoints.py` + `test_documents_contract.py`).

**Modified files**

| File | Change |
|---|---|
| [`backend/app/api/v1/clusters.py`](../../../../backend/app/api/v1/clusters.py) | Add `@router.get("/clusters/{cluster_id}/targets/{target}/documents/{doc_id:path}", ...)` handler after the list handler. |
| [`backend/app/api/v1/clusters.py`](../../../../backend/app/api/v1/clusters.py) | `from backend.app.adapters.protocol import Document` — use `response_model=Document` directly (F3 resolution: no separate router-side schema; the adapter `Document` model is the single source of truth, avoids drift between two schemas with identical shape). |
| [`backend/tests/integration/test_documents_endpoints.py`](../../../../backend/tests/integration/test_documents_endpoints.py) | Add detail-endpoint tests: happy path, doc-missing 404, doc-id-with-slash AC-16. |
| [`backend/tests/contract/test_documents_contract.py`](../../../../backend/tests/contract/test_documents_contract.py) | Add detail-endpoint shape + error envelope tests. |

**Endpoints**

| Method | Path | Success response | Error codes |
|---|---|---|---|
| `GET` | `/api/v1/clusters/{cluster_id}/targets/{target}/documents/{doc_id:path}` | `200` `Document(doc_id, source)` | `CLUSTER_NOT_FOUND` (404), `TARGET_NOT_FOUND` (404), `DOCUMENT_NOT_FOUND` (404, **NEW**), `TARGETS_FORBIDDEN` (403), `CLUSTER_UNREACHABLE` (503) |

**Key interfaces**

```python
# backend/app/api/v1/clusters.py
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
    cluster = await repo.get_cluster(db, cluster_id)
    if cluster is None:
        raise _err(404, "CLUSTER_NOT_FOUND", f"cluster {cluster_id!r} not found", False)
    if not check_target_visible(cluster, target):
        raise _err(404, "TARGET_NOT_FOUND", f"target {target!r} not found", False)
    try:
        async with cluster_svc.acquire_adapter(cluster) as adapter:
            doc = await adapter.get_document(target, doc_id)
    except TargetNotFoundError as exc:
        raise _err(404, "TARGET_NOT_FOUND", f"target {exc.target!r} not found", False) from exc
    except TargetsForbiddenError as exc:
        raise _err(403, "TARGETS_FORBIDDEN", str(exc), False) from exc
    except (ClusterUnreachable, ClusterUnreachableError) as exc:
        raise _err(503, "CLUSTER_UNREACHABLE", str(exc), True) from exc
    if doc is None:
        raise _err(404, "DOCUMENT_NOT_FOUND", f"document {doc_id!r} not found in {target!r}", False)
    log.info(
        "documents.get_requested",
        cluster_id=cluster_id,
        target=target,
        doc_id=doc_id,
        status="ok",
    )
    return doc
```

Cycle-2 F6: the `documents.get_requested` structured-log event matches the spec §13 NFR convention. Same `request_id` propagation pattern as Story 2.2.

**Tasks**

1. Add the route handler.
2. Add `DOCUMENT_NOT_FOUND` to the catalog comment in `clusters.py`.
3. Add contract test asserting `DOCUMENT_NOT_FOUND` envelope shape.
4. Add integration test for doc-id-with-slash round-trip (AC-16): seed a doc with `_id="https://example.com/p/123"`, fetch via `urllib.parse.quote(..., safe="")`, assert the returned doc matches.

**Definition of Done**

- [ ] Endpoint live at the new path with `:path` converter; OpenAPI shows the path-converter behavior.
- [ ] `DOCUMENT_NOT_FOUND` (NEW error code) returned for missing doc.
- [ ] AC-16 (slash in doc_id) green.

---

### Story 2.4 — `?target=` filter on `/api/v1/studies` (backend)

**Outcome:** The studies list endpoint accepts a new optional `?target=<name>` query param. Composes with all existing filters (`status`, `cluster_id`, `since`, `q`, `sort`) via AND. Repo functions `list_studies` and `count_studies` accept `target: str | None = None` kwarg (source-compatible default per D-22).

**New files**

| File | Purpose |
|---|---|
| [`backend/tests/integration/test_studies_target_filter.py`](../../../../backend/tests/integration/test_studies_target_filter.py) | Integration tests: target filter applied alone, composed with cluster_id, composed with status, X-Total-Count matches filter, default (no target) unchanged behavior. |

**Modified files**

| File | Change |
|---|---|
| [`backend/app/api/v1/studies.py`](../../../../backend/app/api/v1/studies.py) | Add `target` param to `list_studies` handler signature. Pass through to `repo.list_studies` and `repo.count_studies`. |
| [`backend/app/db/repo/study.py`](../../../../backend/app/db/repo/study.py) | Add `target: str | None = None` kwarg to both `list_studies` (line 67) and `count_studies` (line 119). Add `if target is not None: stmt = stmt.where(Study.target == target)`. |
| [`backend/tests/contract/test_studies_contract.py`](../../../../backend/tests/contract/test_studies_contract.py) (or its existing equivalent — TBD at impl time) | Add contract test that `?target=` appears in OpenAPI schema and the response shape is unchanged. |

**Endpoints**

| Method | Path | Query params (new only) | Success response | Error codes |
|---|---|---|---|---|
| `GET` | `/api/v1/studies` | `?target=<min_length=1, max_length=256>` (optional, composes with existing filters) | unchanged `StudyListResponse` | unchanged |

**Key interfaces**

```python
# backend/app/api/v1/studies.py (modified signature)
async def list_studies(
    ...,
    cluster_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    target: Annotated[str | None, Query(min_length=1, max_length=256)] = None,  # NEW
    q: Annotated[str | None, Query(min_length=2, max_length=200)] = None,
    sort: Annotated[StudySortKey | None, Query()] = None,
) -> StudyListResponse:
    ...
    rows = await repo.list_studies(db, ..., cluster_id=cluster_id, target=target, q=q, sort=sort)
    total = await repo.count_studies(db, ..., cluster_id=cluster_id, target=target, q=q)

# backend/app/db/repo/study.py (modified signatures)
async def list_studies(
    db: AsyncSession,
    *,
    cursor: tuple[object, str] | None = None,
    limit: int = 50,
    since: datetime | None = None,
    status: StudyStatusFilter | None = None,
    cluster_id: str | None = None,
    target: str | None = None,  # NEW
    q: str | None = None,
    sort: str | None = None,
) -> Sequence[Study]: ...

async def count_studies(
    db: AsyncSession,
    *,
    since: datetime | None = None,
    status: StudyStatusFilter | None = None,
    cluster_id: str | None = None,
    target: str | None = None,  # NEW
    q: str | None = None,
) -> int: ...
```

**Tasks**

1. Run `grep -rn "list_studies\|count_studies" backend/` to confirm no caller passes positional args that would break with the new kwarg insertion. (Verified at plan time: all callers use kwargs.)
2. Update the two repo functions; add the `where` clause.
3. Update the router handler signature; thread the new param.
4. Add integration tests.
5. Add a contract test (cycle-3 F2): `GET /api/v1/studies?target=acme-products-rich&cursor=not-a-valid-cursor` → 422 `VALIDATION_ERROR` with correct envelope. Confirms `target` filter composes with cursor-validation without bypass.
6. Run `make test-unit && make test-integration && make test-contract`.

**Definition of Done**

- [ ] All 12 callers of `list_studies` / `count_studies` (count verified by grep at impl time) continue to compile and pass tests.
- [ ] Integration test asserts AC-12 with concrete inputs (3 studies, 2 with target X, filter returns 2).
- [ ] OpenAPI schema shows `target` as an optional query param on `/api/v1/studies`.

---

### Epic 2 Gate

- [ ] Both new documents endpoints (FR-3, FR-4) live, and the existing `/api/v1/studies` endpoint supports the new `?target=` filter (FR-5 — cycle-2 F4 wording).
- [ ] 6 error codes round-trip with correct envelope (CLUSTER_NOT_FOUND, TARGET_NOT_FOUND, DOCUMENT_NOT_FOUND, TARGETS_FORBIDDEN, CLUSTER_UNREACHABLE, VALIDATION_ERROR).
- [ ] Truncation invariant enforced server-side (sentinel string verifiable).
- [ ] All AC-3, AC-4, AC-5, AC-6, AC-7, AC-8, AC-9, AC-10, AC-12, AC-13, AC-14, AC-15, AC-16 green in integration + contract tests.

---

## Epic 3 — Frontend UI

### Story 3.1 — Indices card on cluster detail page (FR-6)

**Outcome:** [`/clusters/[id]`](../../../../ui/src/app/clusters/[id]/page.tsx) gains an "Indices" card between `ClusterActionBar` and `StudiesByClusterTable`. The card lists indices via the existing `/targets` endpoint with name + formatted doc_count; each row links to `/clusters/[id]/indices/[name]`.

**New files**

| File | Purpose |
|---|---|
| [`ui/src/components/clusters/cluster-detail-indices-card.tsx`](../../../../ui/src/components/clusters/cluster-detail-indices-card.tsx) | The new card component. |
| [`ui/src/__tests__/components/clusters/cluster-detail-indices-card.test.tsx`](../../../../ui/src/__tests__/components/clusters/cluster-detail-indices-card.test.tsx) | Vitest: happy state, empty state, 403 state, 503 state. |

**Modified files**

| File | Change |
|---|---|
| [`ui/src/app/clusters/[id]/page.tsx`](../../../../ui/src/app/clusters/[id]/page.tsx) | Insert `<ClusterDetailIndicesCard clusterId={cluster.id} />` between `<ClusterActionBar cluster={cluster} />` (currently line 30) and the `<Card>` wrapping `<StudiesByClusterTable />` (currently line 31). Verify within ~5 lines at impl time. |
| [`ui/src/lib/api/clusters.ts`](../../../../ui/src/lib/api/clusters.ts) | Add `useClusterTargets(clusterId)` TanStack Query hook. |
| [`ui/src/lib/glossary.ts`](../../../../ui/src/lib/glossary.ts) | Add 2 keys: `cluster.indices_card`, `cluster.target_doc_count`. |
| [`ui/src/__tests__/lib/glossary.test.ts`](../../../../ui/src/__tests__/lib/glossary.test.ts) | New glossary entries flow through the per-key length validators (≤140 chars short, ≤800 chars long) — no hard count update needed. Verify the parity test pattern at impl time. |

**Endpoints used:** `GET /api/v1/clusters/{cluster_id}/targets` (existing).

**Key interfaces**

All path segments (`clusterId`, `target`, `docId`) **MUST** be URL-encoded via `encodeURIComponent` before interpolating into fetch URLs and route hrefs (cycle-3 F5 — required for IDs containing `/`, `%`, `?`, `#`, spaces). Use the existing API client wrapper pattern at [`ui/src/lib/api/`](../../../../ui/src/lib/api/) for consistency.

```typescript
// ui/src/lib/api/clusters.ts
export function useClusterTargets(clusterId: string) {
  return useQuery({
    queryKey: ['cluster', clusterId, 'targets'],
    queryFn: async (): Promise<TargetListResponse> => {
      const res = await fetch(`/api/v1/clusters/${encodeURIComponent(clusterId)}/targets`);
      if (!res.ok) throw await parseApiError(res);
      return res.json();
    },
  });
}

// ui/src/components/clusters/cluster-detail-indices-card.tsx
export interface ClusterDetailIndicesCardProps {
  clusterId: string;
}
export function ClusterDetailIndicesCard({ clusterId }: ClusterDetailIndicesCardProps): JSX.Element;
```

**UI element inventory**

| Element | Type | Data source | User interactions |
|---|---|---|---|
| Card header "Indices" + `<InfoTooltip>` | card | static label | hover → glossary `cluster.indices_card` |
| Indices table | table | `useClusterTargets(clusterId).data` | row click → navigate to `/clusters/[id]/indices/[name]` |
| `Name` column | text | `TargetInfo.name` | — |
| `Documents` column header + `<InfoTooltip>` | column header | static | hover → glossary `cluster.target_doc_count` |
| `Documents` column cell | text | `TargetInfo.doc_count` (formatted with `toLocaleString()`) | — |
| Empty state copy | div | when `data.data.length === 0` | link to cluster-registration runbook |
| Sort: rows rendered in `name` ascending order (cycle-2 F3) | n/a | `[...data].sort((a,b) => a.name.localeCompare(b.name))` before map | — |
| 403 forbidden state | div | when query error is `TARGETS_FORBIDDEN` | inline `"Cluster credentials don't allow listing indices. Register a key with `monitor` privilege."` + link to [`cluster-registration.md`](../../../03_runbooks/cluster-registration.md) |
| 503 unreachable state | div | when query error is `CLUSTER_UNREACHABLE` | inline message + Retry button (calls `refetch()`) |

**Tasks**

1. Add `useClusterTargets` hook to `clusters.ts`. Mirror the existing `useCluster` pattern.
2. Create the `ClusterDetailIndicesCard` component. Use shadcn `<Card>` primitive (matches existing cluster-detail card style) + table elements.
3. Add the 2 glossary keys.
4. Modify `ui/src/app/clusters/[id]/page.tsx` to render the new card.
5. Write 5 vitest tests covering happy / empty / 403 / 503 / sort states (cycle-2 F3 adds the sort test: pass an intentionally-unsorted API mock → assert rendered order is `name` ascending via `localeCompare`).
6. Run `cd ui && pnpm test cluster-detail-indices-card && pnpm test glossary`.

**Definition of Done**

- [ ] AC-1 green (Indices card lists indices on cluster detail).
- [ ] AC-10 partial (403 + 503 inline states render correct copy).
- [ ] 2 new glossary keys; parity test green (51 keys).

---

### Story 3.2 — Index summary page (FR-7)

**Outcome:** New route `/clusters/[id]/indices/[name]/page.tsx` renders index header + schema table + two nav cards. Composes the existing `/targets` + `/schema` responses.

**New files**

| File | Purpose |
|---|---|
| [`ui/src/app/clusters/[id]/indices/[name]/page.tsx`](../../../../ui/src/app/clusters/[id]/indices/[name]/page.tsx) | The summary page. |
| [`ui/src/components/clusters/index-summary-schema-table.tsx`](../../../../ui/src/components/clusters/index-summary-schema-table.tsx) | The schema table (extracted because Story 3.3 + Story 3.4 may want to reuse it via dialog). |
| [`ui/src/__tests__/app/clusters/[id]/indices/[name]/page.test.tsx`](../../../../ui/src/__tests__/app/clusters/[id]/indices/[name]/page.test.tsx) | Vitest: 200 state, 404 `TARGET_NOT_FOUND` state (AC-17), partial-permission state (D-28). |

**Modified files**

| File | Change |
|---|---|
| [`ui/src/lib/api/clusters.ts`](../../../../ui/src/lib/api/clusters.ts) | Add `useClusterSchema(clusterId, target)` TanStack Query hook. |
| [`ui/src/lib/glossary.ts`](../../../../ui/src/lib/glossary.ts) | Add 2 keys: `target.schema`, `target.schema_analyzer`. |
| [`ui/src/__tests__/lib/glossary.test.ts`](../../../../ui/src/__tests__/lib/glossary.test.ts) | New keys flow through per-key validators (≤140 / ≤800). |

**Endpoints used:** `GET /api/v1/clusters/{cluster_id}/targets` + `GET /api/v1/clusters/{cluster_id}/schema?target=<name>` (both existing).

**UI element inventory**

| Element | Type | Data source | User interactions |
|---|---|---|---|
| Page header: `<name>` + dot + formatted `doc_count` + engine type chip | header | filtered `useClusterTargets` data + `useCluster` | — |
| Nav card "Browse documents →" | button | static | click → navigate to `.../documents` |
| Nav card "View studies targeting this index →" | button | static | click → navigate to `/studies?cluster_id=<id>&target=<name>` (D-3 spec note) |
| Schema heading + `<InfoTooltip>` | header | static | hover → glossary `target.schema` |
| Schema table | table | `useClusterSchema(clusterId, target).data.fields` | — |
| `Field` column | text | `FieldSpec.name` | sortable by name |
| `Type` column | text | `FieldSpec.type` | — |
| `Analyzer` column + `<InfoTooltip>` | text + tooltip | `FieldSpec.analyzer` (or `—` when None) | hover header → glossary `target.schema_analyzer` |
| `Documents` column (cycle-3 F1) | text | `FieldSpec.doc_count` (when non-null) | hidden by default behind `<DataTable>` column-visibility toggle per spec FR-7; reveal-and-render flow tested in vitest |
| Partial-permission `doc_count: unknown` italic | italic text | when `/targets` errors with 403 but `/schema` succeeds | — |
| 404 TARGET_NOT_FOUND state | empty | when `/schema` 404 | "Index `<name>` does not exist on this cluster" + breadcrumb |
| Full denial state (cycle-2 F8) | empty | when BOTH `/targets` AND `/schema` return 403 | "Cluster credentials don't allow inspecting this index" + breadcrumb to cluster detail |

**Tasks**

1. Add `useClusterSchema` hook.
2. Create the page component with breadcrumb back to cluster detail.
3. Extract `IndexSummarySchemaTable` for potential reuse.
4. Implement the partial-permission state (per D-28): `if targets.error?.code === 'TARGETS_FORBIDDEN' && schema.data` → render `doc_count: unknown`.
5. Add 2 glossary keys.
6. Vitest covers 200 / 404 / partial-permission states.

**Definition of Done**

- [ ] AC-2 green (summary shows schema + counts + nav cards).
- [ ] AC-17 green (404 target not found).
- [ ] Partial-permission state renders correctly (D-28 / vitest test).
- [ ] 53 glossary keys; parity test green.

---

### Story 3.3 — Documents list page (FR-8)

**Outcome:** New route `/clusters/[id]/indices/[name]/documents/page.tsx` paginates `_id` + truncated `_source` preview via the existing `<DataTable>` cursor primitive.

**New files**

| File | Purpose |
|---|---|
| [`ui/src/app/clusters/[id]/indices/[name]/documents/page.tsx`](../../../../ui/src/app/clusters/[id]/indices/[name]/documents/page.tsx) | The documents list page. |
| [`ui/src/components/clusters/documents-data-table.column-config.tsx`](../../../../ui/src/components/clusters/documents-data-table.column-config.tsx) | Column config for `<DataTable>`. Top-of-file comment: `// No enum filters in V1 and no dynamic field projection UI — see feat_index_document_browser §7.4 / D-21`. |
| [`ui/src/lib/api/documents.ts`](../../../../ui/src/lib/api/documents.ts) | TanStack Query hooks: `useTargetDocuments(clusterId, target, opts)` and `useTargetDocument(clusterId, target, docId)`. |
| [`ui/src/__tests__/app/clusters/[id]/indices/[name]/documents/page.test.tsx`](../../../../ui/src/__tests__/app/clusters/[id]/indices/[name]/documents/page.test.tsx) | Vitest: paginated rendering, truncation sentinel rendering, AC-20 retry refetch (503 then 200). |

**Modified files**

| File | Change |
|---|---|
| [`ui/src/lib/glossary.ts`](../../../../ui/src/lib/glossary.ts) | Add 1 key: `document.truncation_sentinel`. |
| [`ui/src/__tests__/lib/glossary.test.ts`](../../../../ui/src/__tests__/lib/glossary.test.ts) | New key flows through per-key validators (≤140 / ≤800). |

**Endpoints used:** `GET /api/v1/clusters/{cluster_id}/targets/{target}/documents` (NEW, from Story 2.2).

**UI element inventory**

| Element | Type | Data source | User interactions |
|---|---|---|---|
| Page header: `<name>` (linked back to summary) + "<formatted> documents" | header | `X-Total-Count` from response | — |
| `<DataTable>` cursor controls | pagination | TanStack data | Prev / Next clicks toggle cursor |
| `_id` column | monospace | `DocumentSummary.doc_id` | row click → `.../documents/[doc_id]` (URL-encoded) |
| `Preview` column | text | first 3 fields of `source` rendered as `key=value` (truncated values display the sentinel) | — |
| Page size selector | select | 25 / 50 / 100 | changes `?limit` |
| Truncation sentinel cell | text + InfoTooltip | when `source[field] === DOCUMENT_FIELD_TRUNCATED` | hover → glossary `document.truncation_sentinel` |
| Empty state | div | when `data.length === 0` | "No documents in this index." |
| 403 TARGETS_FORBIDDEN state | div | when error.code === `TARGETS_FORBIDDEN` (cycle-2 F8) | inline message matching Cap A's copy + link to cluster-registration runbook |
| 404 TARGET_NOT_FOUND state | div | when error.code === `TARGET_NOT_FOUND` (cycle-2 F8) | "Index `<name>` does not exist on this cluster" + breadcrumb to summary, then cluster detail |
| 503 unreachable state | div | when error.code === `CLUSTER_UNREACHABLE` | Retry button calling `refetch()` (AC-20) |

**Tasks**

1. Add the API hook to `documents.ts`. The hook **MUST** return `{ data: DocumentListResponse, totalCount: number | null }` — `totalCount` is parsed from the response `X-Total-Count` header (F8 resolution). Use a `fetch()` wrapper that reads `res.headers.get('X-Total-Count')` and exposes it alongside the parsed JSON. Pattern (verify against existing hooks like `useStudies` at impl time):
   ```typescript
   const res = await fetch(url);
   if (!res.ok) throw await parseApiError(res);
   const data = await res.json();
   const totalCount = res.headers.get('X-Total-Count');
   return { data, totalCount: totalCount ? parseInt(totalCount, 10) : null };
   ```
2. Use the existing `<DataTable>` cursor pattern via props `cursor`, `next_cursor`, `has_more`, `onCursorChange` (verified at [`data-table.tsx:66-110`](../../../../ui/src/components/common/data-table.tsx) — F10 correction: the primitive does NOT expose a `cursorCodec` prop; it operates on the opaque cursor string directly).
3. Implement the column config. Use a renderer for `Preview` that displays the first 3 source fields.
4. Implement the page component with row click handler that `encodeURIComponent`s the `doc_id` before navigation. The page header reads `totalCount` from the hook and renders `<totalCount>.toLocaleString()` + " documents".
5. Implement the AC-20 retry path: when TanStack Query is in error state with `CLUSTER_UNREACHABLE`, show a Retry button that calls `query.refetch()`.
6. Vitest covers 5 states: happy with pagination, truncation sentinel rendering, 403 `TARGETS_FORBIDDEN` (cycle-2 F8), 404 `TARGET_NOT_FOUND` (cycle-2 F8), 503 `CLUSTER_UNREACHABLE` with retry (AC-20). Use MSW or TanStack test utilities for state transitions. Add an assertion that the header-derived total renders in the page header.
7. Add 1 glossary key.

**Definition of Done**

- [ ] AC-3, AC-4, AC-6, AC-13 green (paginated browse end-to-end with truncation sentinel rendering).
- [ ] AC-20 green (retry refetch).
- [ ] Page-size selector defaults to 25; max 100.

---

### Story 3.4 — Document detail page (FR-9)

**Outcome:** New catch-all route `/clusters/[id]/indices/[name]/documents/[...doc_id]/page.tsx` renders the full `_source` as pretty-printed JSON with a copy-to-clipboard button. Handles `source: null` and `DOCUMENT_NOT_FOUND` (AC-18, AC-9).

**New files**

| File | Purpose |
|---|---|
| [`ui/src/app/clusters/[id]/indices/[name]/documents/[...doc_id]/page.tsx`](../../../../ui/src/app/clusters/[id]/indices/[name]/documents/[...doc_id]/page.tsx) | The detail page (catch-all route per D-17). |
| [`ui/src/__tests__/app/clusters/[id]/indices/[name]/documents/[...doc_id]/page.test.tsx`](../../../../ui/src/__tests__/app/clusters/[id]/indices/[name]/documents/[...doc_id]/page.test.tsx) | Vitest: 200 with full JSON, 404 DOCUMENT_NOT_FOUND, source==null empty state, doc_id with `/` round-trip. |

**Modified files**

| File | Change |
|---|---|
| [`ui/src/lib/glossary.ts`](../../../../ui/src/lib/glossary.ts) | (no new keys — copy button uses inline text per spec §11) |

**Endpoints used:** `GET /api/v1/clusters/{cluster_id}/targets/{target}/documents/{doc_id:path}` (NEW, from Story 2.3).

**UI element inventory**

| Element | Type | Data source | User interactions |
|---|---|---|---|
| Breadcrumb: `<cluster name>` › `<index name>` › `<doc_id>` | nav | derived | each segment clickable except `<doc_id>` |
| Copy-JSON button | button | static | click → `navigator.clipboard.writeText(JSON.stringify(source, null, 2))` |
| Pre-formatted JSON | `<pre>` | `JSON.stringify(source, null, 2)` | — |
| `source: null` empty state | div | when `source === null` | "This document has `_source: false` configured — only the `_id` is retrievable." |
| 404 DOCUMENT_NOT_FOUND state | div | when error.code === `DOCUMENT_NOT_FOUND` | "Document `<doc_id>` does not exist in `<name>`" + breadcrumb back |
| 503 CLUSTER_UNREACHABLE state | div | when error.code === `CLUSTER_UNREACHABLE` (cycle-2 F8) | inline message + Retry button calling `refetch()` |
| 403 TARGETS_FORBIDDEN state | div | when error.code === `TARGETS_FORBIDDEN` (cycle-2 F8) | inline message matching Cap A's copy + breadcrumb back |

**Tasks**

1. Implement the page using the catch-all `params: { doc_id: string[] }` shape. Reconstruct `doc_id` via `params.doc_id.join('/')` — Next.js already URL-decodes route params, so calling `decodeURIComponent` again would corrupt IDs containing literal percent sequences like `a%2Fb` (cycle-2 F5). Verify Next.js 16 behavior at impl time with a vitest case for an ID containing a literal `%2F` (encoded by ES as `a%252Fb` at insert time → URL-encoded as `a%25252Fb` on the wire → Next.js decodes once to `a%252Fb` → joined as `a%252Fb` and passed to API → API forwards encoded to ES as `a%2Fb`).
2. Render JSON via `JSON.stringify(source, null, 2)` inside a `<pre>` with monospace styling.
3. Copy-to-clipboard via `navigator.clipboard.writeText(...)`.
4. Handle `source === null` and `DOCUMENT_NOT_FOUND` states.
5. Vitest tests covering:
   - 200 happy with full JSON rendered.
   - AC-9 / AC-18: `DOCUMENT_NOT_FOUND` and `source === null` states.
   - AC-16: slash-in-doc-id round-trip.
   - Cycle-2 F8: 503 `CLUSTER_UNREACHABLE` (Retry button) and 403 `TARGETS_FORBIDDEN` (matching Cap A copy).
   - Cycle-2 F5: doc_id containing literal `%2F` (encoded as `a%252Fb` on the wire — Next.js decodes once to `a%252Fb`, joined and passed to API).

**Definition of Done**

- [ ] AC-5 green (full JSON shown).
- [ ] AC-9 green (DOCUMENT_NOT_FOUND state).
- [ ] AC-16 green (doc_id with `/` round-trip).
- [ ] AC-18 green (`_source: false` state).

---

### Story 3.5 — LinkedEntitiesRow 5th entry + studies-list `?target=` consumer (FR-10 + FR-5 frontend)

**Outcome:** [`LinkedEntitiesRow`](../../../../ui/src/components/studies/linked-entities-row.tsx) grows from 4 to 5 entries (adds `Index`). The studies list page consumes `?target=` from `searchParams`, threads it through `useStudies`, displays an active filter chip "Target: `<name>`" with an `×` to clear (AC-11, AC-19).

**New files:** none.

**Modified files**

| File | Change |
|---|---|
| [`ui/src/components/studies/linked-entities-row.tsx`](../../../../ui/src/components/studies/linked-entities-row.tsx) | Append a 5th `<Entry>` for `Index` (label="Index", name=`study.target`, href=`/clusters/${study.cluster_id}/indices/${study.target}`, testid="linked-index"). |
| [`ui/src/__tests__/components/studies/linked-entities-row.test.tsx`](../../../../ui/src/__tests__/components/studies/linked-entities-row.test.tsx) | Update existing test count: 4 entries → 5 entries. Add assertion for `linked-index` testid + href. |
| [`ui/src/app/studies/page.tsx`](../../../../ui/src/app/studies/page.tsx) | Parse `target` from `searchParams`; pass to `useStudies`; render an active filter chip. |
| [`ui/src/lib/api/studies.ts`](../../../../ui/src/lib/api/studies.ts) | Add `target` to the `useStudies` query key + URL builder. |
| [`ui/src/__tests__/app/studies/page.test.tsx`](../../../../ui/src/__tests__/app/studies/page.test.tsx) (or the closest existing test) | Add AC-19 test: visit `/studies?target=foo` → chip "Target: foo" renders; click `×` → chip clears, target removed from URL. |

**Endpoints used:** `GET /api/v1/studies?cluster_id=<id>&target=<name>` (extended by Story 2.4).

**UI element inventory** (deltas only)

| Element | Type | Data source | User interactions |
|---|---|---|---|
| `LinkedEntitiesRow` "Index" entry | link + label | `study.target` | click → navigate to index summary |
| Active "Target: `<name>`" filter chip | chip | `searchParams.target` | `×` click → remove `target` from URL, refetch list |

**Tasks**

1. Modify `LinkedEntitiesRow` to append the 5th `<Entry>`.
2. Update the existing vitest test for LinkedEntitiesRow.
3. Modify `studies/page.tsx` to:
   - Read `target` from `searchParams`.
   - Pass to `useStudies` (which threads it into the query key + fetch URL).
   - Render the active filter chip alongside existing chips (cluster + status).
   - **Preserve `target` across pagination, sort changes, and status filter changes** (F9 resolution): every URL update — Next cursor, sort header click, status chip change — must retain `?target=` in the query string until the target chip's `×` is clicked.
4. Update `useStudies` hook signature + query key (the query key array MUST include `target` so cache keys differ across filter values).
5. Add 3 vitest tests asserting AC-19:
   - Initial render: `?target=foo` → chip "Target: foo" present.
   - Pagination/sort preservation: click Next → URL includes both `?cursor=...` AND `?target=foo`; click a sort header → URL includes `?sort=...` AND `?target=foo`; toggle status filter → URL includes `?status=...` AND `?target=foo`.
   - Chip clear: click `×` on the Target chip → URL drops `target=`, other filters preserved, list refetches.

**Definition of Done**

- [ ] AC-11 green (LinkedEntitiesRow has 5 entries).
- [ ] AC-12 green (backend filter works — already covered by Story 2.4's integration test).
- [ ] AC-19 green (filter chip renders + clears).
- [ ] `useStudies` query key includes `target` slot (asserted by component test).

---

### Epic 3 Gate

- [ ] All 3 new routes render correctly (summary, list, detail) with happy + error states; the 2 modified surfaces (cluster detail Indices card, study LinkedEntitiesRow + studies-list filter chip) render correctly (F5 resolution).
- [ ] LinkedEntitiesRow updated.
- [ ] 5 new glossary keys land (`cluster.indices_card`, `cluster.target_doc_count`, `target.schema`, `target.schema_analyzer`, `document.truncation_sentinel`); per-key length validators pass.
- [ ] AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-9, AC-11, AC-13, AC-17, AC-18, AC-19, AC-20 all green in vitest.
- [ ] E2E spec (Story 3.6 below) green.

---

### Story 3.6 — Playwright E2E `index-document-browser.spec.ts`

**Outcome:** A new Playwright spec exercises the full top-down flow + bottom-up entry + studies filter chip against the real backend. No `page.route()` mocking.

**New files**

| File | Purpose |
|---|---|
| [`ui/tests/e2e/index-document-browser.spec.ts`](../../../../ui/tests/e2e/index-document-browser.spec.ts) | Real-backend E2E covering AC-1, AC-2, AC-3, AC-5, AC-11, AC-19. |

**Modified files**

| File | Change |
|---|---|
| [`ui/tests/e2e/helpers/seed.ts`](../../../../ui/tests/e2e/helpers/seed.ts) (or its equivalent helper) | Add a `seedIndexBrowserCorpus(clusterId, indexName)` helper that ensures an index has ≥ 100 docs. May reuse the existing `acme-products-rich` seed or extend it. |

**Tasks**

1. Verify [`scripts/seed_meaningful_demos.py:1040`](../../../../scripts/seed_meaningful_demos.py) seeds enough docs (resolves OQ-1). If not, extend the seed in this PR.
2. Write the spec following the `signup_flow.spec.ts` real-backend pattern.
3. Tests:
   - Top-down: navigate to `/clusters` → click first cluster → assert Indices card → click first index → assert summary → click "Browse documents" → assert ≥ 25 rows → click first row → assert detail with JSON.
   - Bottom-up: navigate to `/studies/<id>` of a seeded study → click `Index:` link → assert summary page loads.
   - Filter chip: from summary, click "View studies targeting this index →" → assert URL is `/studies?cluster_id=<id>&target=<name>` → assert active filter chip rendered.

**Definition of Done**

- [ ] `cd ui && pnpm test:e2e index-document-browser.spec.ts` green.
- [ ] Spec uses `page` for browser interactions; `request` only for setup helpers.

---

## 3) Testing workstream

### 3.1 Unit tests

- Location: `backend/tests/unit/`
- Stories: 1.1, 1.2, 1.3, 2.1.
- Test files created in this plan:
  - `tests/unit/adapters/test_protocol.py` (modified — Story 1.1)
  - `tests/unit/adapters/test_elastic_get_document.py` (new — Story 1.2)
  - `tests/unit/adapters/test_elastic_list_documents.py` (new — Story 1.3)
  - `tests/unit/api/v1/test_documents_cursor.py` (new — Story 2.1)
  - `tests/unit/api/v1/test_documents_fields.py` (new — Story 2.1, cycle-3 F3)
  - `tests/unit/services/test_documents_truncation.py` (new — Story 2.1)
  - `tests/unit/services/test_target_filter.py` (new — Story 2.1)
  - `tests/unit/api/v1/test_strict_query_params.py` (new — Story 2.1)

### 3.2 Integration tests

- Location: `backend/tests/integration/`
- Stories: 2.2, 2.3, 2.4.
- Test files:
  - `tests/integration/test_documents_endpoints.py` (new — Stories 2.2 + 2.3)
  - `tests/integration/test_studies_target_filter.py` (new — Story 2.4)

### 3.3 Contract tests

- Location: `backend/tests/contract/`
- Stories: 2.2, 2.3, 2.4.
- Test files:
  - `tests/contract/test_documents_contract.py` (new — Stories 2.2 + 2.3)
  - `tests/contract/test_studies_contract.py` or existing equivalent (extended — Story 2.4)

Contract tests **MUST** assert:
- `CLUSTER_NOT_FOUND` (404)
- `TARGET_NOT_FOUND` (404)
- `DOCUMENT_NOT_FOUND` (404 — NEW)
- `TARGETS_FORBIDDEN` (403)
- `CLUSTER_UNREACHABLE` (503)
- `VALIDATION_ERROR` (422 — including unknown-query-param path)
- `X-Total-Count` header presence on the list endpoint
- `DocumentListResponse` and `Document` shapes match Pydantic models in OpenAPI

### 3.4 E2E tests

- Location: `ui/tests/e2e/`
- Story 3.6 only.
- Real-backend; no `page.route()`.

### 3.5 Vitest component tests

- Location: `ui/src/__tests__/`
- Stories: 3.1, 3.2, 3.3, 3.4, 3.5.
- Test files:
  - `__tests__/components/clusters/cluster-detail-indices-card.test.tsx` (Story 3.1)
  - `__tests__/app/clusters/[id]/indices/[name]/page.test.tsx` (Story 3.2)
  - `__tests__/app/clusters/[id]/indices/[name]/documents/page.test.tsx` (Story 3.3)
  - `__tests__/app/clusters/[id]/indices/[name]/documents/[...doc_id]/page.test.tsx` (Story 3.4)
  - `__tests__/components/studies/linked-entities-row.test.tsx` (modified — Story 3.5)
  - `__tests__/app/studies/page.test.tsx` or its equivalent (modified — Story 3.5)
  - `__tests__/lib/glossary.test.ts` (modified — Stories 3.1, 3.2, 3.3 — parity count updates)

### 3.6 Existing test impact audit

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `ui/src/__tests__/components/studies/linked-entities-row.test.tsx` | Asserts 4 entries | est. 1-3 | Update to 5 entries (Story 3.5). |
| `ui/src/__tests__/lib/glossary.test.ts` | Per-key validators (≤140 / ≤800 length); no hard count assertion | — | New keys must pass the validators (Stories 3.1, 3.2, 3.3). |
| `ui/src/__tests__/app/clusters/[id]/page.test.tsx` (if exists) | Asserts current 3-section structure | est. 0-2 | Add assertion for Indices card presence (Story 3.1). |
| `backend/tests/integration/test_studies_*.py` | Calls `list_studies` / `count_studies` | est. 5-10 | No change — existing callers use kwargs; new `target` defaults to `None`. |
| `backend/tests/unit/adapters/test_protocol.py:97` | Asserts 5 method names | 1 | Update to 7 names (Story 1.1). |

### 3.7 Migration verification

N/A — no migration in this feature.

### 3.8 CI gates

- [ ] `make test-unit`
- [ ] `make test-integration`
- [ ] `make test-contract`
- [ ] `cd ui && pnpm test`
- [ ] `cd ui && pnpm test:e2e index-document-browser`

---

## 4) Documentation update workstream

### 4.0 Core context files

**`state.md`** — update at the end of Story 3.6:
- [ ] Update active branch to `feat/index-document-browser`
- [ ] Add entry under "Most recent meaningful changes" describing the merged PR
- [ ] No Alembic head change (no migration)

**`architecture.md`** — review at the end of Story 3.6:
- [ ] Likely no changes (architecture is a navigation hub; the topical doc updates below cover the substance)

**`CLAUDE.md`** — update at the end of Story 3.6:
- [ ] Add entry to "Feature Status" table for the merged feature

### 4.1 Architecture docs (`docs/01_architecture`)

- [ ] `adapters.md`: add `get_document` and `list_documents` to the Protocol methods table; document the new `Document`, `AdapterDocumentHit`, `DocumentPage` Pydantic models; note Fusion `NotImplementedError` stub plan.
- [ ] `api-conventions.md`: add `DOCUMENT_NOT_FOUND` to the clusters/documents error-code table; add a "Convention exceptions" subsection noting engine-pass-through endpoints are exempt from `?since=`; note the new `?target=` filter on `/api/v1/studies`.
- [ ] `cluster-lifecycle.md`: update the "6 cluster endpoints" framing to "8 cluster endpoints".
- [ ] `ui-architecture.md`: add a short subsection on the cluster → indices → documents IA.

### 4.2 Product docs (`docs/02_product`)

- [ ] After merge: move `planned_features/feat_index_document_browser/` → `implemented_features/<YYYY_MM_DD>_feat_index_document_browser/` per CLAUDE.md convention.

### 4.3 Runbooks (`docs/03_runbooks`)

- [ ] `cluster-registration.md`: extend the "API key auth" section (currently line 68) with one sentence about the `monitor` privilege requirement (per spec D-15).

### 4.4 Security docs (`docs/04_security`)

- [ ] No update required (no new secrets; read-only surface).

### 4.5 Quality docs (`docs/05_quality`)

- [ ] No update required (test layer convention unchanged).

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

None planned. This is an additive feature with no existing code being replaced or restructured.

### 5.2 Planned refactor tasks

None.

### 5.3 Refactor guardrails

- [ ] No expansion of product scope mid-implementation
- [ ] Helpers in `_documents_cursor.py`, `documents.py`, `_target_filter.py`, `_strict_query_params.py` are not reused by other feature areas in this PR (forward-compat, not active refactor)

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `SearchAdapter` Protocol + `ElasticAdapter` | Stories 1.1–1.3 | Shipped (`infra_adapter_elastic`, 2026-05-10) | None — present |
| `<DataTable>` cursor primitive | Story 3.3 | Shipped (`feat_data_table_primitive`, 2026-05-16) | None — present |
| `<InfoTooltip>` + glossary infra | Stories 3.1–3.3 | Shipped (`feat_contextual_help`, 2026-05-15) | None — present |
| ES service-container in CI | Stories 1.2, 1.3, 2.2, 2.3 | Shipped (per `.github/workflows/pr.yml`) | Integration tests skip when ES not available — fail-loud locally |
| Seeded `acme-products-rich` with ≥ 100 docs | Story 3.6 | Verify at impl time (OQ-1) | Extend seed if insufficient |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `_id` sort fails on supported ES (spec D-26) | Low–Medium | High (whole pagination strategy breaks) | Integration test gates the choice. If fail: fallback to `sort: [{"_doc": "asc"}]`, then PIT + `_shard_doc` if `_doc` also fails. |
| Cursor stability under concurrent inserts | Low | Low (acceptable — flagged in spec §11) | Documented; not a release blocker. |
| Frontend studies-list cache key regression | Low | Medium (filter chip stops invalidating) | Component test asserts `useStudies` query key includes `target`. |
| `_StubAdapter` test breakage from Protocol change | Verified mitigated | Low | Story 1.1 includes the test update. |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| Cluster credentials revoked between page load and refetch | Operator rotates the API key | Endpoint returns 403 `TARGETS_FORBIDDEN`; UI surfaces inline; Retry button does nothing useful | Manual — operator re-registers cluster |
| Index renamed mid-browse | Operator renames `acme-products` → `acme-products-v2` | Next API call returns 404 `TARGET_NOT_FOUND`; UI breadcrumbs back to cluster | Manual — operator navigates fresh |
| Doc deleted between list view and detail click | Concurrent index churn | Detail endpoint returns 404 `DOCUMENT_NOT_FOUND`; UI shows breadcrumb back | Manual — operator paginates |
| Engine returns 5xx mid-pagination | ES OOM or network blip | Endpoint returns 503 `CLUSTER_UNREACHABLE`; UI shows Retry button (AC-20) | Auto — TanStack `refetch()` |
| `_source` truncation sentinel collides with a real document field | Operator's index legitimately has a field whose value is the sentinel string | Sentinel becomes ambiguous (rare in practice — the sentinel includes a non-ASCII ellipsis `…`) | Operator opens detail view; no false positive recovery needed |

---

## 7) Sequencing and parallelization

### Suggested sequence

1. **Epic 1** (Stories 1.1 → 1.2 → 1.3) — adapter Protocol + impls; no dependencies on Epic 2 or 3.
2. **Epic 2** (Stories 2.1 → 2.2 → 2.3 → 2.4) — backend endpoints; depend on Epic 1 (`SearchAdapter.get_document`, `list_documents` must exist).
3. **Epic 3** (Stories 3.1 → 3.2 → 3.3 → 3.4 → 3.5 → 3.6) — frontend surfaces; depend on Epic 2's endpoints.

### Parallelization opportunities

- Within Epic 2, Story 2.1 (helpers) blocks Stories 2.2 and 2.3. Story 2.4 (`?target=` filter) is independent and can run in parallel with 2.2/2.3.
- Within Epic 3, Stories 3.1–3.5 each touch separate route files and can run in parallel after the API endpoints (Epic 2) ship. Story 3.6 (E2E) runs last because it needs all UI surfaces.

---

## 8) Rollout and cutover plan

- **Rollout stages:** none (single PR, read-only surface).
- **Feature flag strategy:** none.
- **Migration / cutover steps:** none (no schema change).
- **Reconciliation:** none.

---

## 9) Execution tracker

### Stories
- [x] Story 1.1 — SearchAdapter Protocol additions
- [x] Story 1.2 — ElasticAdapter.get_document
- [x] Story 1.3 — ElasticAdapter.list_documents
- [x] Story 2.1 — Documents helper module (cursor, truncation, target_filter, strict-query-params)
- [x] Story 2.2 — GET /documents list endpoint
- [x] Story 2.3 — GET /documents/{doc_id:path} detail endpoint
- [x] Story 2.4 — ?target= filter on /studies (backend)
- [x] Story 3.1 — Indices card on cluster detail
- [x] Story 3.2 — Index summary page
- [x] Story 3.3 — Documents list page
- [x] Story 3.4 — Document detail page
- [x] Story 3.5 — LinkedEntitiesRow + studies-list filter chip
- [x] Story 3.6 — Playwright E2E spec

### Blocked items
None.

### Done this sprint
(empty)

---

## 10) Story-by-Story Verification Gate (Agent Checklist)

Before marking any story complete, attach evidence for:

- [ ] Files created/modified match story scope
- [ ] Endpoint contract implemented exactly as documented (method/path/body/status/error code)
- [ ] Key interfaces implemented with compatible signatures
- [ ] Tests added/updated for all relevant layers
- [ ] Commands executed and passed:
  - [ ] `make test-unit`
  - [ ] `make test-integration` (or targeted subset with explanation)
  - [ ] `make test-contract`
  - [ ] `cd ui && pnpm test` (if UI touched)
  - [ ] `cd ui && pnpm test:e2e index-document-browser` (Story 3.6)
- [ ] No migration round-trip required (this feature has no migration)
- [ ] Related docs updated in same PR when behavior/contract changed

---

## 11) Plan consistency review (performed before plan finalized)

1. **Spec ↔ plan endpoint count.** Spec §8.1 has 3 endpoints (2 NEW documents + 1 EXTENSION to /studies). Plan covers all 3 in Stories 2.2, 2.3, 2.4. ✓
2. **Spec ↔ plan error code coverage.** Spec lists 6 codes (`DOCUMENT_NOT_FOUND` NEW + 5 reused). Plan's contract tests cover all 6 in `test_documents_contract.py`. ✓
3. **Spec ↔ plan FR coverage.** All 12 FRs covered in §1 traceability table; each assigned to ≥ 1 story. ✓
4. **Story internal consistency.** Each story's endpoint table, schemas, and DoD reference consistent error codes and HTTP statuses. ✓
5. **Test file count.** 7 unit + 2 integration + 1-2 contract + 6 vitest + 1 E2E = matches story DoD references. ✓
6. **Gate arithmetic.** Epic 1 gate "9 Protocol methods" matches Story 1.1's addition (+2 to existing 7). Epic 2 gate "3 endpoints" matches Stories 2.2 + 2.3 + 2.4. Epic 3 gate covers all 5 frontend FRs. ✓
7. **Open questions.** Spec OQ-1 (seed ≥ 100 docs) is assigned to Story 3.6's Tasks. ✓
8. **UI Guidance completeness.** UI element inventories present on Stories 3.1–3.5. Tooltips inventoried with glossary keys. Insertion point cited for Story 3.1 (line 33-34 of cluster detail page). No legacy-delete >100 LOC, so no Legacy Behavior Parity table required (none of the stories delete user-facing components).
9. **Enumerated value contracts.** No new enum-typed filters in V1. The column-config file explicitly carries a top-of-file comment stating intentional absence of enum filters (Story 3.3 task). ✓
10. **Audit-event coverage.** N/A — read-only feature in MVP1; spec §6 confirms no audit emissions required. ✓
11. **Codebase verification ledger** (see below).

### Codebase verification ledger

| Claim | Verified by | Status |
|---|---|---|
| `ClusterDetailSummary + ClusterActionBar + StudiesByClusterTable` is current cluster detail composition | Read `ui/src/app/clusters/[id]/page.tsx` | Verified |
| `_err()` helper at `clusters.py:93` accepts `(status_code, code, message, retryable)` | Read `backend/app/api/v1/clusters.py:93-98` | Verified |
| `acquire_adapter` context manager at `cluster_svc:232` | grep | Verified |
| `list_studies` / `count_studies` use kwargs (no positional callers) | Verified at plan time; concrete grep audit deferred to Story 2.4 task 1 | Pending |
| `_request(translate_errors: bool = True)` parameter exists | Read `backend/app/adapters/elastic.py:143` | Verified — F7 rejection counter-evidence |
| `<DataTable>` exposes `cursor`, `next_cursor`, `has_more`, `onCursorChange` props (no `cursorCodec`) | Read `ui/src/components/common/data-table.tsx:66-110` | Verified — F10 correction applied |
| `SearchAdapter` has 7 methods today (`health_check / list_targets / get_schema / list_query_parsers / render / search_batch / explain`) | Read `protocol.py` | Verified |
| `_StubAdapter` exists at `test_protocol.py:25-86` | Read | Verified |
| `_StubAdapter` is the ONLY non-`ElasticAdapter` conforming class | grep `class.*SearchAdapter\b` across backend/ | Verified |
| `list_targets()` returns `TargetInfo(name, doc_count)` | Read `elastic.py:411-424` | Verified |
| `search_batch` discards `hits.total.value` | Read `elastic.py:653-660` | Verified — drives D-14 |
| `LinkedEntitiesRow` has 4 entries | Read `ui/src/components/studies/linked-entities-row.tsx` | Verified |
| `prettyPrintJinjaJson` at `ui/src/lib/jinja-json-format.ts:26` | grep | Verified |
| `<DataTable>` cursor primitive at `ui/src/components/common/data-table.tsx` | Read | Verified |
| Cluster detail page lines 33-34 are the insertion point for the Indices card | Re-read at impl time (verified within ~5 lines today) | Pending |
| Glossary parity test asserts 49 keys today | grep `ui/src/__tests__/lib/glossary.test.ts` | Pending (verified at impl time; spec assumes 49 from `feat_contextual_help`) |

---

## 12) Definition of plan done

- [x] Every FR mapped to stories/tasks/tests/docs updates
- [x] Every story includes New files, Modified files, Endpoints (if API), Key interfaces, Tasks, DoD
- [x] Test layers (unit / integration / contract / vitest / e2e) explicitly scoped
- [x] Documentation updates across docs/01-05 planned
- [x] Refactor scope explicit (none)
- [x] Epic gates measurable
- [x] Story-by-Story Verification Gate included (§10)
- [x] Plan consistency review performed (§11)
- [ ] GPT-5.5 cross-model review passed (next step)
