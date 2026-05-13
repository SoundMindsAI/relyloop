# Implementation Plan — feat_query_inline_crud

**Date:** 2026-05-13
**Status:** Draft
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy sources:**
- [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md) — error envelope, cursor pagination, `X-Total-Count`, `?since` contract
- [`docs/01_architecture/data-model.md`](../../../01_architecture/data-model.md) §"queries" + §"judgments" — column-level reference for the tables this feature touches
- [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md) — Next 16 / shadcn / TanStack Query patterns
- `feat_proposals_ui` [implementation plan](../../../00_overview/implemented_features/2026_05_12_feat_proposals_ui/implementation_plan.md) — sibling UI conventions (`<AlertDialog>` reject-dialog, global error-toast wiring, `meta.suppressGlobalErrorToast` precedent)
- `feat_studies_ui` [implementation plan](../../../00_overview/implemented_features/2026_05_12_feat_studies_ui/implementation_plan.md) — `<CursorPaginator>`, `<EmptyState>`, enum source-of-truth gate

---

## 0) Planning principles

- Single-phase, no migrations. Existing `queries` table + `judgments.query_id` FK are sufficient.
- Backend ships first: every frontend story depends on the new endpoints existing in OpenAPI so `lib/types.ts` can be regenerated.
- Reuse existing infrastructure: `_err()` helper, cursor base64 envelope idiom, `apiClient` retry contract, global `MutationCache.onError`, shadcn `<AlertDialog>` / `<Popover>` / `<Dialog>` / `<Table>` / `<Button>` primitives (already present), `<CursorPaginator>`, `PROPOSAL_STATUS_VALUES`-style enum patterns (this feature adds no new enums).
- One carve-out from "no local mutation `onError`": `useDeleteQuery` opts out of the global handler via `meta.suppressGlobalErrorToast` because the 409 `QUERY_HAS_JUDGMENTS` toast needs a Sonner `action` slot (clickable link to the offending judgment list). Locked in spec §FR-4 / §FR-6.
- Two-SQL design for `count_and_sample_judgment_refs` — one aggregate, one sample. Called only on the 409 cold path (after the FK `IntegrityError` rollback), so the two-query cost is paid only when the operator actually hit a 409.
- ID-only cursor (UUIDv7 is lexically time-ordered already). New helpers `_encode_query_cursor` / `_decode_query_cursor` live alongside the existing query-set cursor helpers in the same router file — NOT shared with the query-set list cursor (different shape).
- `?since` filter via UUIDv7 lower-bound id construction — no schema change.

## 1) Scope traceability (FR → epics/stories → tests)

| FR | Epic / Story | Test files | Spec ACs |
|---|---|---|---|
| FR-1 (list endpoint w/ judgment_count, cursor, since) | Epic 1 / Stories 1.1 + 1.2 + 1.3 | `backend/tests/integration/test_query_sets_router_queries.py`, `backend/tests/integration/test_query_repo_extensions.py`, `backend/tests/contract/test_query_sets_api_contract.py`, `backend/tests/unit/api/test_query_cursor_helpers.py`, `backend/tests/unit/api/test_uuidv7_since_helper.py` | AC-1, AC-2, AC-3, AC-4, AC-25, AC-26 |
| FR-2 (PATCH endpoint, empty-PATCH no-op, model_validator) | Epic 2 / Stories 2.1 + 2.2 | `backend/tests/integration/test_query_sets_router_queries.py`, `backend/tests/integration/test_query_repo_extensions.py`, `backend/tests/contract/test_query_sets_api_contract.py`, `backend/tests/unit/api/test_update_query_request.py` | AC-5..AC-12, AC-28 |
| FR-3 (DELETE + FK guard + 409 envelope + OpenAPI wiring) | Epic 3 / Stories 3.1 + 3.2 | `backend/tests/integration/test_query_sets_router_queries.py`, `backend/tests/integration/test_judgment_repo_query_helpers.py`, `backend/tests/contract/test_query_sets_api_contract.py` | AC-13, AC-14, AC-15, AC-16, AC-17, AC-24 |
| FR-4 (frontend table + inline edit/delete + 409 toast with link) | Epic 4 / Stories 4.1 + 4.2 + 4.3 | `ui/src/components/query-sets/__tests__/queries-table.test.tsx`, `…/edit-query-popover.test.tsx`, `…/edit-metadata-dialog.test.tsx`, `…/delete-query-dialog.test.tsx` | AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-27 |
| FR-5 (repo + service layer functions) | Stories 1.2, 1.3, 2.2, 3.2 (transitive) | same as FR-1/2/3 | covered transitively |
| FR-6 (frontend TanStack hooks) | Epic 4 / Story 4.0 | `ui/src/lib/api/__tests__/queries.test.tsx` | AC-21 |

No FRs are deferred — single-phase deliverable. Running-study protection is captured for a future `infra_running_study_protection` chore per spec §19 (Decision log) and **does not block this plan**.

## 2) Delivery structure

**Conventions (project-specific):**

- All backend code is Python 3.13; one file per aggregate in `backend/app/db/repo/`; routers in `backend/app/api/v1/`; Pydantic v2 schemas in `backend/app/api/v1/schemas.py`.
- Repo functions: first arg `db: AsyncSession`; use `db.flush()` (caller commits via `await db.commit()` at the router layer).
- Routers raise via the existing `_err(status_code, code, message, retryable)` helper at [`backend/app/api/v1/query_sets.py:48-52`](../../../../backend/app/api/v1/query_sets.py#L48-L52). Reuse it for all 4 error codes this feature introduces.
- New `__init__.py` exports updated via `__all__`.
- All endpoints declare `response_model=<Schema>` so OpenAPI exposes the contract. The DELETE endpoint additionally declares `responses={409: {"model": QueryHasJudgmentsEnvelope}}`.
- Pydantic models: `ConfigDict(extra="forbid")` on every request body that should reject unknown fields.
- All new files are TypeScript / TSX under `ui/src/`.
- Pages: `ui/src/app/<route>/page.tsx` (Next 16 App Router, `'use client'`).
- Per-page components: `ui/src/components/query-sets/<component>.tsx` (this feature uses the existing `query-sets/` folder — already established by `add-queries-dialog.tsx`, `queries-table` is the new sibling).
- TanStack hooks: extend `ui/src/lib/api/query-sets.ts` (do NOT split into a new file — the existing module already owns query-sets-and-children).
- Mutations use the global `MutationCache.onError` handler unless they need a custom toast renderer (the one carve-out is `useDeleteQuery` for the 409 with action link).
- Frontend tests live at `ui/src/__tests__/<mirror-source-tree>/<file>.test.tsx` OR co-located `ui/src/components/query-sets/__tests__/`. This plan uses co-located for component tests to match the existing convention (`ui/src/components/proposals/__tests__/`).
- Date strings → ISO 8601; render via `new Date(s).toLocaleString()` (none needed in this feature — `queries` has no timestamps).

**AI Agent Execution Protocol:**

0. Read `state.md` + `architecture.md` + this plan + the spec.
1. **Backend first**, in order: Story 1.2 (repo) → Story 1.3 (judgment-count helper) → Story 1.1 (router GET) → Story 2.2 (repo update + schema) → Story 2.1 (router PATCH) → Story 3.2 (repo delete + count_and_sample helper) → Story 3.1 (router DELETE + OpenAPI wiring).
2. Run `make test-unit && make test-integration && make test-contract` after each backend story. Coverage gate ≥80%.
3. **Frontend** after the backend is merged (or at minimum after `make up && curl /openapi.json` confirms the new endpoints), in order: Story 4.0 (hooks + regenerate `lib/types.ts`) → Story 4.1 (`<QueriesTable>` + page integration) → Story 4.2 (edit popover + metadata dialog) → Story 4.3 (delete dialog + 409 toast).
4. Run `cd ui && pnpm lint && pnpm typecheck && pnpm test && pnpm build` after each frontend story.
5. Run `bash scripts/ci/verify_enum_source_of_truth.sh` after Story 4.0 (this plan does NOT add any new enums — gate should be a no-op for this feature).
6. **Docs sweep last** (Story 5.1): update `api-conventions.md`, `mvp1-user-stories.md`, `ui-debugging.md`, `state.md`, plus delete the placeholder card reference in `query-sets/[id]/page.tsx`.

---

## Epic 1 — Backend list endpoint (FR-1)

Ships `GET /api/v1/query-sets/{set_id}/queries` with cursor pagination, `?since` UUIDv7 lower-bound filter, `X-Total-Count` header, and per-row `judgment_count` derived field.

### Story 1.2 — Repo extensions: `get_query`, `count_queries_for_set`, `list_queries_for_set_cursor`

**Outcome:** [`backend/app/db/repo/query.py`](../../../../backend/app/db/repo/query.py) exports three new functions consuming the existing `Query` ORM model. No DB schema change. All three follow the existing repo conventions (`db: AsyncSession` first arg; `db.flush()` for staging if needed; caller commits at the router layer).

**New files** — none.

**Modified files**

| File | Change |
|---|---|
| `backend/app/db/repo/query.py` | Add `get_query(db, query_id) → Query \| None`, `count_queries_for_set(db, query_set_id, *, since_lower_bound_id=None) → int`, `list_queries_for_set_cursor(db, query_set_id, *, after_id=None, limit=50, since_lower_bound_id=None) → list[Query]`. Reorder existing `list_queries_for_set` (sort by `id ASC`) is preserved as-is for the worker path; new cursor function lives alongside it. |
| `backend/app/db/repo/__init__.py` | Re-export the three new functions in `__all__` (alphabetical insertion). |

**Endpoints** — none (repo layer; no API surface).

**Key interfaces**

```python
# db/repo/query.py
async def get_query(db: AsyncSession, query_id: str) -> Query | None: ...
async def count_queries_for_set(
    db: AsyncSession,
    query_set_id: str,
    *,
    since_lower_bound_id: str | None = None,
) -> int: ...
async def list_queries_for_set_cursor(
    db: AsyncSession,
    query_set_id: str,
    *,
    after_id: str | None = None,
    limit: int = 50,
    since_lower_bound_id: str | None = None,
) -> list[Query]: ...
```

Implementation notes:
- `list_queries_for_set_cursor` SQL: `SELECT * FROM queries WHERE query_set_id = :id AND (id > :after_id OR :after_id IS NULL) AND (id >= :since_lower_bound_id OR :since_lower_bound_id IS NULL) ORDER BY id ASC LIMIT :limit`. UUIDv7 lexical ordering makes this a deterministic time-ordered scan.
- `count_queries_for_set` accepts only `since_lower_bound_id` — `?cursor` is not part of the total count (per `api-conventions.md` §"Pagination" — `X-Total-Count` is independent of pagination but respects filters).

**Tasks**
1. Add the three functions to `backend/app/db/repo/query.py` with module-docstring update describing the cursor semantics.
2. Update `backend/app/db/repo/__init__.py` `__all__` exports.
3. Run `make typecheck` to verify SQLAlchemy AsyncSession types resolve.

**Definition of Done**
- [ ] All three functions exist and are exported via `__all__`.
- [ ] `backend/tests/integration/test_query_repo_extensions.py` (**owned by THIS story**) exercises each function with happy paths + edge cases (empty set, only-cursor, only-since, both, neither, limit-equals-total). The router-layer integration tests (`test_query_sets_router_queries.py`) come with Story 1.1 — repo-vs-router test ownership is split cleanly.
- [ ] `make typecheck` green.
- [ ] `make test-integration` green for this story's new test file.

### Story 1.3 — Batch judgment-count helper

**Outcome:** A single SQL query returns a `dict[query_id, int]` of judgment counts for a paginated page of queries. Called from the router's GET handler AFTER the page is fetched. Single GROUP BY over `judgments.query_id IN (<page>)` — no N+1.

**New files** — none.

**Modified files**

| File | Change |
|---|---|
| `backend/app/db/repo/judgment.py` | Add `count_judgments_per_query(db, query_ids: Sequence[str]) → dict[str, int]`. Returns counts keyed by query_id; queries with zero judgments get a `0` value (the helper post-fills missing keys so the router doesn't have to). |
| `backend/app/db/repo/__init__.py` | Re-export `count_judgments_per_query` in `__all__`. |

**Key interfaces**

```python
# db/repo/judgment.py
async def count_judgments_per_query(
    db: AsyncSession,
    query_ids: Sequence[str],
) -> dict[str, int]: ...
```

SQL implementation: `SELECT query_id, COUNT(*) FROM judgments WHERE query_id = ANY(:query_ids) GROUP BY query_id`. **The helper itself** post-fills missing keys with 0 so callers always get a dict with exactly `len(query_ids)` entries. The router's later use of `counts.get(r.id, 0)` is harmless defense-in-depth.

**Tasks**
1. Add the function. Empty input → return `{}` short-circuit.
2. Export via `__all__`.

**Definition of Done**
- [ ] Function exists and is exported.
- [ ] **Test added to `backend/tests/integration/test_query_repo_extensions.py` in THIS story** (the file is created by Story 1.2; Story 1.3 extends it): empty input → `{}`, 3 queries with mixed counts → correct dict, 3 queries with zero judgments → all-zero dict (proves post-fill works).
- [ ] Asserts the index `judgments_list_query_idx` (already exists) covers the predicate.

### Story 1.1 — Router `GET /api/v1/query-sets/{set_id}/queries`

**Outcome:** New endpoint live with cursor pagination, `?since` filter, `X-Total-Count` header, per-row `judgment_count`. Returns 404 `QUERY_SET_NOT_FOUND` if the parent set is missing; 422 `VALIDATION_ERROR` on bad cursor.

**New files** — none.

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/query_sets.py` | Add `_encode_query_cursor(query_id: str) → str` + `_decode_query_cursor(raw: str) → str` helpers (id-only base64 envelope). Add `_uuidv7_lower_bound_from_iso(since: datetime) → str` helper that constructs a UUIDv7-with-zero-randomness from `since.timestamp() * 1000` ms. Add the GET endpoint. |
| `backend/app/api/v1/schemas.py` | Add `QueryRow` + `QueryListResponse` Pydantic models. |

**Endpoints**

| Method | Path | Request | Success response | Error codes |
|---|---|---|---|---|
| `GET` | `/api/v1/query-sets/{set_id}/queries?cursor&limit&since` | — (query params only) | `200` `QueryListResponse` + `X-Total-Count` header | `QUERY_SET_NOT_FOUND` (404), `VALIDATION_ERROR` (422 — bad cursor / bad `since` ISO-8601 / limit out of [1, 200]) |

**Key interfaces**

```python
# api/v1/query_sets.py
def _encode_query_cursor(query_id: str) -> str:
    return base64.urlsafe_b64encode(json.dumps({"id": query_id}).encode()).decode()

_UUID_HEX_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

def _decode_query_cursor(raw: str) -> str:
    try:
        decoded = json.loads(base64.urlsafe_b64decode(raw.encode()).decode())
    except Exception as exc:
        raise _err(422, "VALIDATION_ERROR", f"invalid cursor: {exc}", False) from exc
    if not isinstance(decoded, dict):
        raise _err(422, "VALIDATION_ERROR", "cursor must decode to a JSON object", False)
    id_value = decoded.get("id")
    if not isinstance(id_value, str) or not _UUID_HEX_RE.match(id_value):
        raise _err(422, "VALIDATION_ERROR", "cursor.id must be a UUIDv7 string", False)
    return id_value

def _uuidv7_lower_bound_from_iso(since: datetime) -> str:
    # UUIDv7 = 48-bit ms timestamp + 4-bit version + 12-bit rand_a + 2-bit variant + 62-bit rand_b
    # Lower-bound = ts_ms in the first 48 bits, all other bits zero.
    ms = int(since.timestamp() * 1000)
    high = (ms << 16) | 0x7000  # version 7 in the right nibble
    return f"{(high >> 32) & 0xFFFFFFFF:08x}-{(high >> 16) & 0xFFFF:04x}-{high & 0xFFFF:04x}-8000-000000000000"
```

Router handler skeleton (analogous to existing `list_query_sets` at [`query_sets.py:129-157`](../../../../backend/app/api/v1/query_sets.py#L129-L157)):

```python
@router.get(
    "/query-sets/{query_set_id}/queries",
    response_model=QueryListResponse,
    tags=["query-sets"],
)
async def list_queries_in_set(
    query_set_id: str,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
    since: Annotated[datetime | None, Query()] = None,
) -> QueryListResponse:
    qs = await repo.get_query_set(db, query_set_id)
    if qs is None:
        raise _err(404, "QUERY_SET_NOT_FOUND", f"query set {query_set_id} not found", False)
    after_id = _decode_query_cursor(cursor) if cursor else None
    since_lb = _uuidv7_lower_bound_from_iso(since) if since else None
    rows = await repo.list_queries_for_set_cursor(
        db, query_set_id, after_id=after_id, limit=limit, since_lower_bound_id=since_lb
    )
    total = await repo.count_queries_for_set(db, query_set_id, since_lower_bound_id=since_lb)
    response.headers["X-Total-Count"] = str(total)
    counts = await repo.count_judgments_per_query(db, [r.id for r in rows])
    data = [QueryRow(
        id=r.id, query_text=r.query_text, reference_answer=r.reference_answer,
        query_metadata=r.query_metadata, judgment_count=counts.get(r.id, 0),
    ) for r in rows]
    next_cursor = _encode_query_cursor(rows[-1].id) if rows and len(rows) == limit else None
    return QueryListResponse(data=data, next_cursor=next_cursor, has_more=next_cursor is not None)
```

**Pydantic schemas**

```python
class QueryRow(BaseModel):
    id: str
    query_text: str
    reference_answer: str | None
    query_metadata: dict[str, Any] | None
    judgment_count: int


class QueryListResponse(BaseModel):
    data: list[QueryRow]
    next_cursor: str | None
    has_more: bool
```

**Tasks**
1. Add the three helpers + the router endpoint.
2. Add the two Pydantic models to `schemas.py`.
3. Verify the route appears in OpenAPI (`curl localhost:8000/openapi.json | jq '.paths | keys | .[] | select(contains("queries"))'`).

**Definition of Done**
- [ ] All AC-1/2/3/4/25/26 pass at the integration layer (`test_query_sets_router_queries.py`).
- [ ] OpenAPI schema exposes `QueryListResponse` as the GET 200 schema.
- [ ] `make test-integration` + `make test-contract` green.

---

## Epic 2 — Backend PATCH (FR-2)

### Story 2.2 — Repo `update_query` + `UpdateQueryRequest` schema

**Outcome:** Repo `update_query` applies ONLY the keys present in `fields_set` (preserves "omitted = no change" semantics). `UpdateQueryRequest` Pydantic model rejects extra fields + rejects explicit `query_text: null` via `@model_validator`.

**New files** — none.

**Modified files**

| File | Change |
|---|---|
| `backend/app/db/repo/query.py` | Add `update_query(db, query_id, *, fields_set: dict) → Query`. Applies only keys present in `fields_set`. Returns the refreshed row. |
| `backend/app/db/repo/__init__.py` | Re-export `update_query` in `__all__`. |
| `backend/app/api/v1/schemas.py` | Add `UpdateQueryRequest` Pydantic model. |

**Key interfaces**

```python
# db/repo/query.py
async def update_query(
    db: AsyncSession,
    query_id: str,
    *,
    fields_set: dict[str, Any],
) -> Query:
    """Apply ONLY the keys present in ``fields_set``. Caller commits.

    The router resolves the body via ``body.model_dump(exclude_unset=True)`` so
    omitted keys never reach this function. Explicit null values DO reach it and
    overwrite the column to NULL (used for `reference_answer` and
    `query_metadata`)."""
    stmt = (
        sqlalchemy.update(Query)
        .where(Query.id == query_id)
        .values(**fields_set)
        .returning(Query)
    )
    result = await db.execute(stmt)
    row = result.scalar_one()
    await db.flush()
    return row
```

**Pydantic schemas**

```python
class UpdateQueryRequest(BaseModel):
    """PATCH /query-sets/{set_id}/queries/{query_id} body."""
    model_config = ConfigDict(extra="forbid")
    query_text: str | None = Field(default=None, min_length=1, max_length=4000)
    reference_answer: str | None = None  # explicit None → NULL the column
    query_metadata: dict[str, Any] | None = None  # whole-object replace

    @model_validator(mode="after")
    def _reject_explicit_null_query_text(self) -> "UpdateQueryRequest":
        if "query_text" in self.model_fields_set and self.query_text is None:
            raise ValueError("query_text cannot be null (column is NOT NULL)")
        return self
```

**Tasks**
1. Add `update_query` to `query.py`. Use SQLAlchemy `update(...).values(**fields_set).returning(Query)` so the refreshed row is returned in one round-trip.
2. Add `UpdateQueryRequest` to `schemas.py` (after `BulkQueriesResponse`).
3. Empty `fields_set` (`{}`) → return the current row unchanged. Implementation: short-circuit `if not fields_set: return await get_query(db, query_id)`.

**Definition of Done**
- [ ] `update_query` exported via `__all__`.
- [ ] `UpdateQueryRequest` validates: extra="forbid", min_length on `query_text`, explicit-null `query_text` rejection.
- [ ] Unit test `test_update_query_request.py` covers all three constraints + empty body.
- [ ] Integration test `test_query_repo_extensions.py` covers `update_query` happy paths (single field, multi-field, all-null path, empty `fields_set` no-op).

### Story 2.1 — Router `PATCH /api/v1/query-sets/{set_id}/queries/{query_id}`

**Outcome:** Endpoint live with 200 returning the updated `QueryRow` (including refreshed `judgment_count`); 404 on missing parent OR missing query OR cross-set query; 422 on bad body; 200 no-op on empty body `{}`.

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/query_sets.py` | Add the PATCH endpoint. Reuses `get_query_set` lookup + new `get_query` repo + `update_query` repo + `count_judgments_per_query` for response shaping. |

**Endpoints**

| Method | Path | Request | Success response | Error codes |
|---|---|---|---|---|
| `PATCH` | `/api/v1/query-sets/{set_id}/queries/{query_id}` | `UpdateQueryRequest` | `200` `QueryRow` | `QUERY_SET_NOT_FOUND` (404), `QUERY_NOT_FOUND` (404 — also for cross-set; anti-enumeration), `VALIDATION_ERROR` (422) |

**Key interfaces**

```python
@router.patch(
    "/query-sets/{query_set_id}/queries/{query_id}",
    response_model=QueryRow,
    tags=["query-sets"],
)
async def update_query_endpoint(
    query_set_id: str,
    query_id: str,
    body: UpdateQueryRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> QueryRow:
    qs = await repo.get_query_set(db, query_set_id)
    if qs is None:
        raise _err(404, "QUERY_SET_NOT_FOUND", f"query set {query_set_id} not found", False)
    query = await repo.get_query(db, query_id)
    if query is None or query.query_set_id != query_set_id:
        # Anti-enumeration: same shape as truly missing.
        raise _err(404, "QUERY_NOT_FOUND", f"query {query_id} not found", False)
    fields_set = body.model_dump(exclude_unset=True)
    updated = await repo.update_query(db, query_id, fields_set=fields_set)
    await db.commit()
    counts = await repo.count_judgments_per_query(db, [query_id])
    return QueryRow(
        id=updated.id, query_text=updated.query_text,
        reference_answer=updated.reference_answer, query_metadata=updated.query_metadata,
        judgment_count=counts.get(query_id, 0),
    )
```

**Tasks**
1. Add the endpoint.
2. Confirm `body.model_dump(exclude_unset=True)` correctly differentiates omitted vs explicit-null keys.
3. Emit a structlog `info` event on every PATCH: `logger.info("query_updated", query_set_id=..., query_id=..., fields_changed=sorted(fields_set.keys()), latency_ms=...)`. **Do NOT log** `query_text` / `reference_answer` / `query_metadata` values themselves — only the list of keys that changed. `request_id` is bound at middleware level (see existing routes for the pattern; no per-call wiring needed).

**Definition of Done**
- [ ] All AC-5..AC-12 + AC-28 pass at the integration layer.
- [ ] OpenAPI exposes `QueryRow` as the PATCH 200 schema.
- [ ] Contract test asserts `UpdateQueryRequest` is in `components.schemas`.
- [ ] Integration test asserts the `query_updated` log event fires with `fields_changed` matching the body keys (via `caplog`/structlog test capture) AND that no log record from this route ever contains the strings of `query_text` / `reference_answer` / `query_metadata` values (defense-in-depth grep across all captured records).

---

## Epic 3 — Backend DELETE + FK guard (FR-3)

### Story 3.2 — Repo `delete_query` + `count_and_sample_judgment_refs`

**Outcome:** Repo issues the raw DELETE (the router catches `IntegrityError`). Sample helper returns the 4-field `JudgmentRefCounts` shape used by the 409 envelope.

**New files** — none.

**Modified files**

| File | Change |
|---|---|
| `backend/app/db/repo/query.py` | Add `delete_query(db, query_id) → None`. Just issues the DELETE; caller catches `IntegrityError` and rollbacks. |
| `backend/app/db/repo/judgment.py` | Add `count_and_sample_judgment_refs(db, query_id, *, sample_limit=10) → JudgmentRefCounts`. Two SQL queries (aggregate + sample). |
| `backend/app/db/repo/__init__.py` | Re-export both. |
| `backend/app/db/repo/judgment.py` | Define repo-internal dataclasses `JudgmentListRefRow(id: str, name: str)` and `JudgmentRefCounts(judgment_count: int, list_count: int, sample_lists: list[JudgmentListRefRow], overflow_count: int)`. These are NOT Pydantic wire models — they stay in the repo layer to avoid a repo→API dependency. The DELETE router maps them into the `JudgmentListRef` / `QueryHasJudgmentsDetail` / `QueryHasJudgmentsEnvelope` Pydantic models defined in `schemas.py` (Story 3.1). |

**Key interfaces**

```python
# db/repo/query.py
async def delete_query(db: AsyncSession, query_id: str) -> None:
    """Issue the raw DELETE. Caller MUST catch IntegrityError + rollback."""
    stmt = sqlalchemy.delete(Query).where(Query.id == query_id)
    await db.execute(stmt)
    await db.flush()  # forces the FK check NOW so the router can catch it

# db/repo/judgment.py
@dataclass(frozen=True)
class JudgmentListRefRow:
    """Repo-layer row shape — distinct from the API-layer JudgmentListRef
    Pydantic model so the repo doesn't depend on backend/app/api/."""
    id: str
    name: str


@dataclass(frozen=True)
class JudgmentRefCounts:
    judgment_count: int
    list_count: int
    sample_lists: list[JudgmentListRefRow]  # alphabetised by name
    overflow_count: int


async def count_and_sample_judgment_refs(
    db: AsyncSession,
    query_id: str,
    *,
    sample_limit: int = 10,
) -> JudgmentRefCounts: ...
```

SQL for the sample (alphabetical):

```sql
-- Query A (aggregate):
SELECT COUNT(*) AS judgment_count,
       COUNT(DISTINCT judgment_list_id) AS list_count
FROM judgments
WHERE query_id = :id;

-- Query B (sample):
SELECT DISTINCT j.judgment_list_id, l.name
FROM judgments j
JOIN judgment_lists l ON l.id = j.judgment_list_id
WHERE j.query_id = :id
ORDER BY l.name ASC
LIMIT :sample_limit;
```

`overflow_count = max(0, list_count - sample_limit)`.

**Tasks**
1. Add `delete_query` with the explicit `await db.flush()` so the FK violation surfaces synchronously.
2. Add `count_and_sample_judgment_refs` with the two-SQL design.
3. Add the `JudgmentListRefRow` + `JudgmentRefCounts` dataclasses to `backend/app/db/repo/judgment.py`. **All API-layer wire models (`JudgmentListRef`, `QueryHasJudgmentsDetail`, `QueryHasJudgmentsEnvelope`) are owned by Story 3.1.** Story 3.2 is repo-only.

**Definition of Done**
- [ ] Both functions exported.
- [ ] `test_judgment_repo_query_helpers.py` covers AC-14/15 boundary cases (0 / 1 / 10 / 11 / 15 lists) + alphabetical ordering assertion.

### Story 3.1 — Router `DELETE /api/v1/query-sets/{set_id}/queries/{query_id}` + OpenAPI wiring

**Outcome:** Endpoint live. 204 on success; 404 on missing-parent/missing-query/cross-set (anti-enumeration); 409 `QUERY_HAS_JUDGMENTS` on FK violation with the structured envelope. OpenAPI exposes `QueryHasJudgmentsEnvelope` as the 409 response schema.

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/query_sets.py` | Add the DELETE endpoint with `responses={409: {"model": QueryHasJudgmentsEnvelope}}`. |
| `backend/app/api/v1/schemas.py` | Add `JudgmentListRef`, `QueryHasJudgmentsDetail`, `QueryHasJudgmentsEnvelope` Pydantic models. |

**Endpoints**

| Method | Path | Request | Success response | Error codes |
|---|---|---|---|---|
| `DELETE` | `/api/v1/query-sets/{set_id}/queries/{query_id}` | — | `204` (empty body) | `QUERY_SET_NOT_FOUND` (404), `QUERY_NOT_FOUND` (404 incl. cross-set anti-enumeration), `QUERY_HAS_JUDGMENTS` (409 with `QueryHasJudgmentsEnvelope`) |

**Key interfaces**

```python
@router.delete(
    "/query-sets/{query_set_id}/queries/{query_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={409: {"model": QueryHasJudgmentsEnvelope}},
    tags=["query-sets"],
)
async def delete_query_endpoint(
    query_set_id: str,
    query_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    qs = await repo.get_query_set(db, query_set_id)
    if qs is None:
        raise _err(404, "QUERY_SET_NOT_FOUND", f"query set {query_set_id} not found", False)
    query = await repo.get_query(db, query_id)
    if query is None or query.query_set_id != query_set_id:
        raise _err(404, "QUERY_NOT_FOUND", f"query {query_id} not found", False)
    try:
        await repo.delete_query(db, query_id)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        refs = await repo.count_and_sample_judgment_refs(db, query_id)
        # Map repo-layer JudgmentListRefRow → API-layer JudgmentListRef
        wire_lists = [JudgmentListRef(id=r.id, name=r.name) for r in refs.sample_lists]
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "QUERY_HAS_JUDGMENTS",
                "message": (
                    f"query {query_id} has {refs.judgment_count} judgments across "
                    f"{refs.list_count} judgment list(s)"
                    + (f" (showing first {len(wire_lists)})" if refs.overflow_count else "")
                    + "; remove the parent judgment list(s) first"
                ),
                "retryable": False,
                "judgment_lists": [r.model_dump() for r in wire_lists],
                "overflow_count": refs.overflow_count,
            },
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

**Pydantic schemas**

```python
class JudgmentListRef(BaseModel):
    id: str
    name: str


class QueryHasJudgmentsDetail(BaseModel):
    error_code: Literal["QUERY_HAS_JUDGMENTS"]
    message: str
    retryable: Literal[False]
    judgment_lists: list[JudgmentListRef]
    overflow_count: int


class QueryHasJudgmentsEnvelope(BaseModel):
    detail: QueryHasJudgmentsDetail
```

**Tasks**
1. Add the three Pydantic models.
2. Add the endpoint with the `responses={409: …}` wiring so OpenAPI documents the structured detail.
3. Verify the OpenAPI schema exposes `QueryHasJudgmentsEnvelope` and that `judgment_lists` + `overflow_count` appear in the 409 example.
4. Emit a structlog `info` event on success: `logger.info("query_deleted", query_set_id=..., query_id=..., had_judgments=False, latency_ms=...)`. On 409, emit `logger.info("query_deleted_blocked", query_set_id=..., query_id=..., had_judgments=True, list_count=refs.list_count, latency_ms=...)`. **Do NOT log** judgment-list names or `query_text` values (`list_count` is a structural count, safe).

**Definition of Done**
- [ ] All AC-13/14/15/16/17/24 pass at the integration layer.
- [ ] OpenAPI contract test (`test_query_sets_api_contract.py`) asserts `QueryHasJudgmentsEnvelope` is in `components.schemas` AND that the DELETE route's 409 response references it.
- [ ] Static-grep test confirms no log line ever emits `query_text` or `query_metadata` values from this router (defense-in-depth for the §10 Threat 3 audit-log policy when MVP2 lands).
- [ ] Integration test asserts the `query_deleted` event fires on 204 with `had_judgments=False`, and `query_deleted_blocked` fires on 409 with `had_judgments=True, list_count=N`.

---

## Epic 4 — Frontend (FR-4, FR-6)

### Story 4.0 — Extend `lib/api/query-sets.ts` with per-query hooks

**Outcome:** `useQueries(querySetId, filter)`, `useUpdateQuery(querySetId)`, `useDeleteQuery(querySetId)` exist. `useDeleteQuery` opts out of the global error toast via `meta: { suppressGlobalErrorToast: true }` and adds a local `onError` to render the 409 toast with action link OR delegate to `toToastMessage(err)` for any other error code.

**New files** — none.

**Modified files**

| File | Change |
|---|---|
| `ui/src/lib/api/query-sets.ts` | Add 3 hooks + the `QueriesFilter`, `QueriesPage` types. Regenerate `ui/src/lib/types.ts` via `pnpm openapi-typescript` to pick up the new backend types. |
| `ui/src/lib/types.ts` | Auto-regenerated — new types `QueryRow`, `QueryListResponse`, `UpdateQueryRequest`, `QueryHasJudgmentsEnvelope`, `JudgmentListRef`. |

**Key interfaces**

```typescript
// Re-exported from regenerated types.ts:
export type QueryRow = components['schemas']['QueryRow'];
export type QueryListResponse = components['schemas']['QueryListResponse'];
export type UpdateQueryRequest = components['schemas']['UpdateQueryRequest'];
export type QueryHasJudgmentsEnvelope = components['schemas']['QueryHasJudgmentsEnvelope'];
export type JudgmentListRef = components['schemas']['JudgmentListRef'];

export type QueriesPage = QueryListResponse & { totalCount: number };

export interface QueriesFilter {
  cursor?: string | undefined;
  limit?: number | undefined;
  since?: string | undefined;  // ISO 8601
}

export function useQueries(
  querySetId: string,
  filter: QueriesFilter = {},
): UseQueryResult<QueriesPage, ApiError> {
  const { cursor, limit, since } = filter;
  return useQuery<QueriesPage, ApiError>({
    queryKey: ['query-sets', querySetId, 'queries', { cursor, limit, since }],
    queryFn: async () => {
      const { data, headers } = await apiClient.get<QueryListResponse>(
        `/api/v1/query-sets/${querySetId}/queries`,
        { params: { cursor, limit, since } },
      );
      return { ...data, totalCount: Number(headers.get('X-Total-Count') ?? 0) };
    },
  });
}

export function useUpdateQuery(querySetId: string): UseMutationResult<
  QueryRow,
  ApiError,
  { queryId: string; patch: UpdateQueryRequest }
> {
  const qc = useQueryClient();
  return useMutation<QueryRow, ApiError, { queryId: string; patch: UpdateQueryRequest }>({
    mutationFn: async ({ queryId, patch }) => {
      const { data } = await apiClient.patch<QueryRow>(
        `/api/v1/query-sets/${querySetId}/queries/${queryId}`,
        patch,
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['query-sets', querySetId, 'queries'] });
      qc.invalidateQueries({ queryKey: ['query-sets', querySetId] });
    },
    // NO local onError — global MutationCache.onError handles it.
  });
}

// useDeleteQuery — the carve-out. Custom 409 toast with action link.
// REQUIRES `onOpenJudgmentList` callback so the toast action can fire navigation —
// the hook itself can't call `useRouter()` from inside `onError`. Consuming
// component (DeleteQueryDialog) calls `useRouter()` and passes `router.push` in.
export interface DeleteQueryOptions {
  onOpenJudgmentList: (judgmentListId: string) => void;
  onSuccess?: () => void;
}

export function useDeleteQuery(
  querySetId: string,
  options: DeleteQueryOptions,
): UseMutationResult<void, ApiError, string> {
  const qc = useQueryClient();
  return useMutation<void, ApiError, string>({
    meta: { suppressGlobalErrorToast: true },  // <-- opt out of global
    mutationFn: async (queryId) => {
      await apiClient.delete(`/api/v1/query-sets/${querySetId}/queries/${queryId}`);
    },
    onSuccess: () => {
      toast.success('Query deleted');
      qc.invalidateQueries({ queryKey: ['query-sets', querySetId, 'queries'] });
      qc.invalidateQueries({ queryKey: ['query-sets', querySetId] });
      options.onSuccess?.();
    },
    onError: (err) => {
      if (isApiError(err) && err.errorCode === 'QUERY_HAS_JUDGMENTS') {
        const detail = err.detail as QueryHasJudgmentsEnvelope['detail'];
        const first = detail.judgment_lists[0];
        const totalLists = detail.judgment_lists.length + detail.overflow_count;
        const noun = totalLists === 1 ? 'judgment list' : 'judgment lists';
        const msg =
          `${totalLists} ${noun} reference this query.` +
          (detail.overflow_count > 0 ? ` (${detail.overflow_count} more not shown.)` : '');
        toast.error(msg, first
          ? { action: {
              label: `Open ${first.name} →`,
              onClick: () => options.onOpenJudgmentList(first.id),
            } }
          : undefined);
      } else if (isApiError(err)) {
        toast.error(toToastMessage(err));  // delegate to canonical formatting
      } else {
        toast.error('Unknown error');
      }
    },
  });
}
```

**Tasks**
1. Run `pnpm openapi-typescript` to regenerate `ui/src/lib/types.ts` against the running backend's OpenAPI schema (requires Story 1.1 + 2.1 + 3.1 merged and the backend running).
2. Add the three hook functions to `query-sets.ts`. The `useDeleteQuery` signature REQUIRES the `onOpenJudgmentList` callback — there is no fall-back-no-action-link path. The consuming `<DeleteQueryDialog>` calls `useRouter()` at component scope and passes `router.push` in.
3. `useUpdateQuery` does NOT call `toast.success(...)` itself — the consuming `<EditQueryPopover>` / `<EditMetadataDialog>` shows the success toast (so the message can be context-specific, e.g. "Query updated" vs "Metadata cleared"). The hook just invalidates caches.

**Definition of Done**
- [ ] `ui/src/lib/types.ts` regenerated and committed.
- [ ] Three hooks exported from `query-sets.ts`.
- [ ] `useDeleteQuery` has `meta: { suppressGlobalErrorToast: true }` (verified by msw handler-hit-count + spy on `toast.error`).
- [ ] `queries.test.tsx` covers all three hooks + the 409-with-link path + the non-409 fallback to `toToastMessage`.

### Story 4.1 — `<QueriesTable>` replaces placeholder card on `/query-sets/[id]`

**Outcome:** New `<QueriesTable>` component renders rows with `query_text` / `reference_answer` / metadata indicator / `judgment_count` / row-actions (3 inline icon-buttons: Edit / Metadata / Delete). Replaces the placeholder card at [`page.tsx:61-72`](../../../../ui/src/app/query-sets/[id]/page.tsx#L61-L72). Pagination via existing `<CursorPaginator>`.

**Row actions UX (zero new deps):** Spec §5 forbids new npm packages. `<DropdownMenu>` is NOT present today, so this story uses **inline action buttons** in the row-actions column (no kebab). Three icon-buttons sit side-by-side: ✏️ Edit (opens popover), `{ }` Metadata (opens dialog), 🗑 Delete (opens alert dialog). At narrow viewports they collapse to icon-only via existing Tailwind responsive classes. This is the same pattern proposals-table uses (no dropdown).

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/query-sets/queries-table.tsx` | The table component. Renders rows + 3-button row-actions + pagination controls. Internal state: page cursor stack, selected query for inline edit, selected query for metadata edit, selected query for delete. |

**Modified files**

| File | Change |
|---|---|
| `ui/src/app/query-sets/[id]/page.tsx` | REPLACE lines 61-72 (the placeholder card) with `<QueriesTable querySetId={query.data.id} />`. Remove the `<code>chore_query_inline_edit_delete</code>` bareword. |

**Tasks**
1. Create `queries-table.tsx` using shadcn `<Table>` primitive + inline action buttons (3 icon-buttons per row) + existing `<CursorPaginator>`.
2. Edit `page.tsx` lines 61-72 to render `<QueriesTable querySetId={query.data.id} />`.
3. Confirm the page-size selector array `[10, 25, 50, 100]` matches the existing `<CursorPaginator>` API.

**Definition of Done**
- [ ] AC-18 passes.
- [ ] `page.tsx` no longer contains the `chore_query_inline_edit_delete` bareword (grep gate).
- [ ] `queries-table.test.tsx` covers: render-empty / render-with-rows / page-size selector + pagination / icon-buttons RENDER with correct `aria-label` values ("Edit query", "Edit query metadata", "Delete query"). Overlay-opening assertions land in Stories 4.2 / 4.3 (the overlays don't exist yet at Story 4.1's completion). Story 4.1 stubs the click handlers with `() => void` placeholders that the later stories replace.

### Story 4.2 — `<EditQueryPopover>` + `<EditMetadataDialog>`

**Outcome:** Clicking the row's Edit icon-button opens an anchored `<Popover>` with `query_text` + `reference_answer` text fields. Clicking the row's Metadata icon-button (or the metadata indicator badge) opens a modal `<Dialog>` with a JSON textarea + Save / Cancel / "Clear metadata" buttons.

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/query-sets/edit-query-popover.tsx` | Inline edit popover. `react-hook-form` + Zod (`z.string().min(1).max(4000)` on `query_text`). |
| `ui/src/components/query-sets/edit-metadata-dialog.tsx` | Metadata dialog with JSON textarea + Clear button. |

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/query-sets/queries-table.tsx` | Wire the row's Edit / Metadata icon-button + metadata-indicator-click handlers to open the respective overlays. |

**Tasks**
1. Build `<EditQueryPopover>` using shadcn `<Popover>`. Submit calls `useUpdateQuery({queryId, patch})`. PATCH body sends ONLY changed keys (use react-hook-form's `formState.dirtyFields`).
2. Build `<EditMetadataDialog>` with a textarea pre-filled with `JSON.stringify(query_metadata, null, 2)`. Validate via Zod refine: the parsed value MUST be a plain object (not array, not scalar, not null). Pseudocode: `z.string().refine(s => { try { const p = JSON.parse(s); return p !== null && typeof p === 'object' && !Array.isArray(p); } catch { return false; } }, 'Must be a JSON object')`. On Save, send `{query_metadata: parsedObject}`. On Clear-metadata, send `{query_metadata: null}` (NOT `{}` — explicit null is the SQL-NULL signal per spec AC-27). Tests assert that arrays, scalars (numbers, strings, booleans), and the literal `null` are all rejected with the inline error AND no PATCH request fires.
3. Add `data-testid` attributes for test selection.

**Definition of Done**
- [ ] AC-19 + AC-22 + AC-23 + AC-27 pass.
- [ ] Component tests cover: happy-path submit (incl. success-toast assertion via `toast.success` spy — text "Query updated" for edit popover, "Metadata updated" for dialog save, "Metadata cleared" for the Clear button), invalid-JSON inline error + no PATCH, Clear-metadata sends `{"query_metadata": null}`.

### Story 4.3 — `<DeleteQueryDialog>` + 409 toast with action link

**Outcome:** Clicking the row's Delete icon-button opens shadcn `<AlertDialog>` with destructive confirm. Submit calls `useDeleteQuery`. On 409 `QUERY_HAS_JUDGMENTS`, toast renders the affected-list message + an action button navigating to `/judgments/{first_id}`.

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/query-sets/delete-query-dialog.tsx` | AlertDialog wrapper. Calls `useRouter()` at component scope and passes `(id) => router.push(`/judgments/${id}`)` as the `onOpenJudgmentList` callback to `useDeleteQuery` so the 409 toast action navigates to the correct path. |

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/query-sets/queries-table.tsx` | Wire the row's Delete icon-button to open `<DeleteQueryDialog query={row} />`. |

**Analogous markup pattern — from `reject-dialog.tsx:30-90`:**

```tsx
{/* Delete confirm — adapted from reject-dialog.tsx pattern */}
<AlertDialog open={open} onOpenChange={setOpen}>
  <AlertDialogContent>
    <AlertDialogHeader>
      <AlertDialogTitle>Delete query?</AlertDialogTitle>
      <AlertDialogDescription>
        This permanently removes the query. Judgments must be removed first.
      </AlertDialogDescription>
    </AlertDialogHeader>
    <AlertDialogFooter>
      <AlertDialogCancel disabled={del.isPending}>Cancel</AlertDialogCancel>
      <AlertDialogAction
        onClick={(event) => {
          event.preventDefault();  // keep dialog open during in-flight
          del.mutate(query.id, {
            onSuccess: () => setOpen(false),
            // onError falls through to the hook's local 409 handler
          });
        }}
        disabled={del.isPending}
        className="bg-destructive text-destructive-foreground"
        data-testid="confirm-delete-query"
      >
        {del.isPending ? 'Deleting…' : 'Delete query'}
      </AlertDialogAction>
    </AlertDialogFooter>
  </AlertDialogContent>
</AlertDialog>
```

**Tasks**
1. Build `<DeleteQueryDialog>` mirroring the reject-dialog pattern. Confirm button must call `event.preventDefault()` to keep the dialog open during the in-flight POST (per `feat_proposals_ui` Decision: `AlertDialogAction requires event.preventDefault()`).
2. Inside `<DeleteQueryDialog>`, call `useRouter()` at component scope. Construct the callback `const onOpenJudgmentList = (id: string) => router.push(\`/judgments/${id}\`)`. Pass it into `useDeleteQuery(querySetId, { onOpenJudgmentList })`. Tests assert the spied callback receives the affected list's id AND the toast's action label is `Open <first name> →`.

**Definition of Done**
- [ ] AC-20 passes (409 toast renders the affected-list link, Q3 still in the table).
- [ ] Confirm button shows "Deleting…" while pending; cannot double-submit.
- [ ] Component test covers: happy path 204 → "Query deleted" toast + row removed; 409 path → toast + action link + row still present + click on action link fires `router.push` with `/judgments/{first_id}`; non-409 error path falls through to `toToastMessage`; **XSS-safety case** — 409 payload contains `{judgment_lists: [{id: "...", name: "<script>alert('xss')</script>"}], overflow_count: 0}`, assert the toast action label DOM contains the literal `<script>...</script>` characters as text content (not as an injected element) and no script executes. Use Testing Library's `getByText(/<script>/)` + check `document.querySelector('script[data-test-injected]')` returns null.

---

## Epic 5 — Docs sweep + state.md update

### Story 5.1 — Documentation updates

**Outcome:** All affected docs updated; `state.md` reflects the feature shipping; backlog row removed.

**Modified files**

| File | Change |
|---|---|
| `docs/01_architecture/api-conventions.md` | Append `GET /api/v1/query-sets/{set_id}/queries` to the §"Pagination" MVP1-active endpoint list. |
| `docs/02_product/mvp1-user-stories.md` | Extend US-08 with a one-line note: "per-query inline edit + delete via `feat_query_inline_crud` (PR #<N>)". |
| `docs/03_runbooks/ui-debugging.md` | Append a "Per-query editing" section covering: how to trigger 409, what the toast says, follow-the-link UX, common error codes. |
| `state.md` | Move `feat_query_inline_crud` from `/pipeline candidates` to "Most recent meaningful changes." Decrement backlog count. |

**Tasks**
1. Update each file with the precise additions listed.
2. Run `pre-commit run --all-files` to catch trailing whitespace / EOF newline issues.

**Definition of Done**
- [ ] All 4 doc files updated.
- [ ] `state.md` backlog row removed.
- [ ] Pre-commit gates green.

---

## UI Guidance

### Reference: current component structure

`ui/src/app/query-sets/[id]/page.tsx` (105 lines total):

| Section | Lines |
|---|---|
| Imports | 1-12 |
| `RouteProps` interface | 13-15 |
| `QuerySetDetailView` opening + state | 17-21 |
| Back link | 23-31 |
| Loading + error branches | 32-39 |
| Header (name + cluster + count + Add button) | 41-53 |
| Description card (conditional) | 54-60 |
| **Placeholder card — REPLACED by `<QueriesTable>`** | **61-72** |
| Associated judgment lists card | 73-83 |
| AddQueriesDialog + GenerateJudgmentsDialog | 84-95 |
| Default export | 101-104 |

State variables:
- `addQueriesOpen: boolean` (line 19) — `<AddQueriesDialog>` open state
- `generateOpen: boolean` (line 20) — `<GenerateJudgmentsDialog>` open state

After Story 4.1, the placeholder card at 61-72 becomes `<QueriesTable querySetId={query.data.id} />`. No state additions to `page.tsx` — `<QueriesTable>` owns its own state.

### Insertion point

`page.tsx` lines 61-72. Delete the entire `<Card>...</Card>` block (12 lines including the `chore_query_inline_edit_delete` bareword) and replace with the single line `<QueriesTable querySetId={query.data.id} />`.

### Analogous markup patterns

**Pattern: shadcn `<Table>` — from `proposals-table.tsx` (existing):**

```tsx
{/* Existing shadcn table — copy-pasteable for queries-table.tsx */}
<Table>
  <TableHeader>
    <TableRow>
      <TableHead>Query text</TableHead>
      <TableHead>Reference answer</TableHead>
      <TableHead>Metadata</TableHead>
      <TableHead className="w-24 text-right">Judgments</TableHead>
      <TableHead className="w-12" />
    </TableRow>
  </TableHeader>
  <TableBody>
    {rows.map((row) => (
      <TableRow key={row.id} data-testid={`row-${row.id}`}>
        <TableCell className="max-w-md truncate" title={row.query_text}>
          {row.query_text.length > 100 ? row.query_text.slice(0, 97) + '…' : row.query_text}
        </TableCell>
        <TableCell
          className="max-w-xs"
          title={row.reference_answer ?? 'Reference answer not set'}
        >
          {row.reference_answer === null
            ? '—'
            : row.reference_answer.length > 50
              ? row.reference_answer.slice(0, 49) + '…'
              : row.reference_answer}
        </TableCell>
        <TableCell>
          <Badge
            variant={row.query_metadata ? 'default' : 'secondary'}
            onClick={() => openMetadataDialog(row)}
            className="cursor-pointer"
          >
            {row.query_metadata ? 'Set' : '—'}
          </Badge>
        </TableCell>
        <TableCell className="text-right">{row.judgment_count.toLocaleString()}</TableCell>
        <TableCell className="text-right">
          {/* Inline icon-button trio — zero new deps per spec §5 */}
          <div className="flex justify-end gap-1">
            <EditQueryPopover
              querySetId={querySetId}
              query={row}
              trigger={
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label="Edit query"
                  title="Edit query text and reference answer"
                  data-testid={`edit-${row.id}`}
                >
                  ✏️
                </Button>
              }
            />
            <Button
              variant="ghost"
              size="icon"
              onClick={() => openMetadataDialog(row)}
              aria-label="Edit query metadata"
              title="Edit query metadata"
              data-testid={`meta-${row.id}`}
            >
              {'{ }'}
            </Button>
            <DeleteQueryDialog
              querySetId={querySetId}
              query={row}
              trigger={
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label="Delete query"
                  title={row.judgment_count > 0
                    ? `Delete blocked — query has ${row.judgment_count} judgment(s). Remove the parent judgment list first.`
                    : 'Delete query'}
                  className="text-destructive"
                  data-testid={`delete-${row.id}`}
                >
                  🗑
                </Button>
              }
            />
          </div>
        </TableCell>
      </TableRow>
    ))}
  </TableBody>
</Table>
```

**Pattern: shadcn `<AlertDialog>` — from `reject-dialog.tsx:30-90` (existing):** see Story 4.3 analogous markup.

**Pattern: react-hook-form `<Popover>` — from `judgment-override-popover.tsx` (existing in `ui/src/components/judgments/`):**

```tsx
<Popover open={open} onOpenChange={setOpen}>
  <PopoverTrigger asChild>{trigger}</PopoverTrigger>
  <PopoverContent className="w-80">
    <Form {...form}>
      <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-3">
        <FormField
          control={form.control}
          name="query_text"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Query text</FormLabel>
              <FormControl><Textarea {...field} rows={3} /></FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        {/* reference_answer field */}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
          <Button type="submit" disabled={update.isPending}>
            {update.isPending ? 'Saving…' : 'Save'}
          </Button>
        </div>
      </form>
    </Form>
  </PopoverContent>
</Popover>
```

### Layout and structure

- Queries table is a full-width section between the header and the "Associated judgment lists" card.
- Pagination controls (`<CursorPaginator>`) live below the table, right-aligned.
- The total-count indicator ("248 queries total") sits above the table, left-aligned.
- Responsive: on narrow viewports, the metadata column collapses to icon-only (`<Badge>` without label).

### Confirmation/modal dialog pattern

See Story 4.3 analogous markup for the `<AlertDialog>` pattern.

### Visual consistency table

| New element | CSS class / pattern source |
|---|---|
| Table | `<Table>` from `ui/src/components/ui/table.tsx` (shadcn) |
| Truncated text cells | `className="max-w-md truncate" title={fullText}` — matches `proposals-table.tsx` pattern |
| Metadata indicator | `<Badge variant={...}>` from `ui/src/components/ui/badge.tsx` |
| Row-actions cell | 3 inline `<Button variant="ghost" size="icon">` from `ui/src/components/ui/button.tsx` (Edit / Metadata / Delete) — no DropdownMenu |
| Edit popover | `<Popover>` from `ui/src/components/ui/popover.tsx` |
| Metadata dialog | `<Dialog>` from `ui/src/components/ui/dialog.tsx` |
| Delete confirm | `<AlertDialog>` from `ui/src/components/ui/alert-dialog.tsx` |
| Destructive button | `className="bg-destructive text-destructive-foreground"` — matches reject-dialog.tsx |
| Loading state on confirm | `{mutation.isPending ? 'Deleting…' : 'Delete query'}` — matches reject-dialog.tsx pattern |
| Toast | `toast.error(msg, {action: {label, onClick}})` from `sonner` |

### Component composition

- `<QueriesTable querySetId={string} />` — owns its pagination state + opens overlays via internal state. Page passes only `querySetId`.
- `<EditQueryPopover querySetId={string} query={QueryRow} trigger={ReactNode} />` — uncontrolled-by-parent; the Popover wraps `<PopoverTrigger asChild>{trigger}</PopoverTrigger>` so anchoring to the row's Edit button is intrinsic (no `open`/`onOpenChange` needed at the parent). The `trigger` is the Edit icon-button rendered by `<QueriesTable>`. Internal state controls open/close on save/cancel.
- `<EditMetadataDialog querySetId={string} query={QueryRow} open={bool} onOpenChange={(b) => void} />` — controlled (modal dialog needs page-level open coordination because either the kebab Metadata button OR the row's Metadata indicator badge can open it).
- `<DeleteQueryDialog querySetId={string} query={QueryRow} trigger={ReactNode} />` — uncontrolled-by-parent; wraps `<AlertDialogTrigger asChild>{trigger}</AlertDialogTrigger>` so the row's Delete icon-button is the trigger. Internally calls `useRouter()` then `useDeleteQuery(querySetId, { onOpenJudgmentList: (id) => router.push(`/judgments/${id}`) })`.

### Interaction behavior table

| User action | Frontend behavior | API call |
|---|---|---|
| Open `/query-sets/{id}` | `useQuerySet(id)` + `useQueries(id, { limit: 50 })` fire on mount | `GET /api/v1/query-sets/{id}`, `GET /api/v1/query-sets/{id}/queries?limit=50` |
| Click Next page | Update local cursor state | `GET /api/v1/query-sets/{id}/queries?cursor=…&limit=50` |
| Click row's Edit icon | Open `<EditQueryPopover>` | (none yet) |
| Submit edit popover | Submit form via `useUpdateQuery` | `PATCH /api/v1/query-sets/{id}/queries/{query_id}` with the dirty fields |
| Click metadata indicator OR row's Metadata icon | Open `<EditMetadataDialog>` | (none yet) |
| Save in metadata dialog (valid JSON) | Submit via `useUpdateQuery` | `PATCH …` with `{query_metadata: parsedObject}` |
| Click "Clear metadata" in dialog | Submit via `useUpdateQuery` | `PATCH …` with `{query_metadata: null}` |
| Click row's Delete icon | Open `<DeleteQueryDialog>` | (none yet) |
| Confirm delete (no judgments) | `useDeleteQuery` → success toast | `DELETE …` → 204 |
| Confirm delete (with judgments) | `useDeleteQuery` → 409 → custom toast with action link | `DELETE …` → 409 |

### Handler function patterns

See "Analogous markup patterns" above for the confirm handler. The metadata-dialog Save handler:

```typescript
const onSubmit = (values: { metadata_json: string }) => {
  let parsed: unknown;
  try { parsed = JSON.parse(values.metadata_json); }
  catch { form.setError('metadata_json', { message: 'Invalid JSON' }); return; }
  update.mutate(
    { queryId: query.id, patch: { query_metadata: parsed as Record<string, unknown> } },
    { onSuccess: () => onOpenChange(false) },
  );
};

const onClear = () => {
  update.mutate(
    { queryId: query.id, patch: { query_metadata: null } },
    { onSuccess: () => onOpenChange(false) },
  );
};
```

### Information architecture placement

- Lives at `/query-sets/[id]` — same page as today, REPLACING the placeholder card between the description card and the associated-judgment-lists card.
- No nav-tree changes. No new pages. No new routes.
- Operators discover the feature implicitly — they visit a query-set detail page (e.g., from the studies-create flow) and see a real table where the placeholder card used to be.

### Tooltips and contextual help

| Element | Tooltip text | Trigger | Placement | Markup |
|---|---|---|---|---|
| `query_text` cell (truncated) | full `query_text` value | hover | top (native HTML `title` attribute) | `<TableCell title={row.query_text}>` |
| `reference_answer` cell ("—") | "Reference answer not set" | hover | top | `<TableCell title={row.reference_answer ?? 'Reference answer not set'}>` |
| `judgment_count` column header | "Number of (query, doc) ratings across all judgment lists for this query" | hover | top | `<TableHead title="...">Judgments</TableHead>` |
| Delete icon-button (with `judgment_count > 0`) | "Delete blocked — query has N judgments. Remove the parent judgment list first." | hover | top | `<Button title={...} variant="ghost" size="icon">🗑</Button>` |
| "Edit query metadata" dialog | "JSON object. Whole-object replace — explicit null removes the field, omitted keys leave existing fields unchanged on PATCH (this dialog sends the whole edited object)." | always visible | inline (below textarea) | `<p className="text-xs text-muted-foreground">…</p>` |

### Legacy behavior parity

No legacy behavior parity table — no user-facing component >100 LOC is being deleted or migrated in this plan. The placeholder card at `page.tsx:61-72` is 12 lines with no validation, no inflight state, no error handling, no tooltips, and no confirmation dialog — it's a static info card. Replacing it is a pure addition, not a migration.

### Client-side persistence

None. No `localStorage` or `sessionStorage` usage. All UI state is in-memory React state.

---

## 3) Testing workstream (required)

### 3.1 Unit tests
- Location: `backend/tests/unit/`
- Scope: pure helpers only. NO DB-backed assertions (SQLite-in-memory doesn't enforce FK and lacks JSONB — moved those to integration per spec §14 + cycle-1 GPT-5.5 F7).
- Tasks:
  - [ ] `backend/tests/unit/api/test_query_cursor_helpers.py` — `_encode_query_cursor` / `_decode_query_cursor` round-trip + invalid-cursor → 422 raised.
  - [ ] `backend/tests/unit/api/test_uuidv7_since_helper.py` — `_uuidv7_lower_bound_from_iso(datetime)` returns a UUIDv7-shaped string with the correct 48-bit timestamp prefix and zero randomness. Verify boundary at ms-precision.
  - [ ] `backend/tests/unit/api/test_update_query_request.py` — `UpdateQueryRequest` validates: `extra="forbid"` rejects unknown keys, `min_length=1` rejects empty `query_text`, `max_length=4000` rejects long `query_text`, `@model_validator` rejects explicit-null `query_text`, empty body `{}` validates cleanly (no-op path).
- DoD:
  - [ ] All three files exist with the assertions above; `make test-unit` green.

### 3.2 Integration tests
- Location: `backend/tests/integration/`
- Scope: DB-backed router + repo tests. Uses the existing service-container Postgres + async session fixture.
- Tasks:
  - [ ] `backend/tests/integration/test_query_sets_router_queries.py` — covers AC-1 through AC-17 PLUS AC-24 (cross-set DELETE 404) PLUS AC-25/26 (`?since` filter semantics + cursor combination) PLUS AC-28 (empty-PATCH no-op).
  - [ ] `backend/tests/integration/test_query_repo_extensions.py` — covers `get_query`, `count_queries_for_set` (with/without `since`), `list_queries_for_set_cursor` (cursor, since, both, limit, empty), `update_query` (single-field, multi-field, null-set, empty-fields-set short-circuit), `delete_query` (raises `IntegrityError` when judgments exist).
  - [ ] `backend/tests/integration/test_judgment_repo_query_helpers.py` — covers `count_and_sample_judgment_refs` across 0 / 1 / 10 / 11 / 15 lists; alphabetical ordering; overflow_count math.
  - [ ] `backend/tests/integration/test_query_delete_race.py` — covers spec §10 Threat 4. Uses `asyncio.gather(delete_query_via_router(...), bulk_create_judgments_via_repo(...))` with the FK constraint enforced by Postgres. Asserts the post-condition: EITHER `delete=204 and judgments.count == 0`, OR `delete=409 and judgments.count > 0`. Runs the assertion 20× to surface any flakiness in the contract.
- DoD:
  - [ ] Happy path + critical failure paths covered. `make test-integration` green.
  - [ ] Each new test file isolates its data via the existing async session fixture (no global state pollution).

### 3.3 Contract tests
- Location: `backend/tests/contract/`
- Scope: endpoint shape, status codes, machine-readable error codes, OpenAPI surface.
- Tasks:
  - [ ] `backend/tests/contract/test_query_sets_api_contract.py` (new file) — assert: (a) all 3 new endpoints appear in OpenAPI under `/api/v1/query-sets/...`; (b) `QueryListResponse` is the GET 200 response_model; (c) `QueryRow` is the PATCH 200 response_model; (d) `QueryHasJudgmentsEnvelope` is the DELETE 409 response model with `judgment_lists` + `overflow_count` fields present; (e) each of the 4 new error codes (`QUERY_SET_NOT_FOUND` — reused, `QUERY_NOT_FOUND`, `QUERY_HAS_JUDGMENTS`, `VALIDATION_ERROR`) appears in the relevant route's source via grep-based static check; (f) static grep confirms no log line in `query_sets.py` ever logs `query_text` or `query_metadata` values from this router.
- DoD:
  - [ ] All 4 error codes are asserted via grep. OpenAPI contract assertions pass. `make test-contract` green.

### 3.4 E2E tests
- Location: `ui/tests/e2e/`
- Scope: **NONE for MVP1.** Per spec §14, real-backend E2E coverage for `/query-sets/[id]` does not exist today and adding the first E2E test against a real backend on this feature is out of scope. Captured as `chore_query_inline_crud_e2e` idea file deferred from this implementation (created during Story 5.1's docs sweep).
- Tasks:
  - [ ] Create `docs/02_product/planned_features/chore_query_inline_crud_e2e/idea.md` capturing the deferred E2E suite (4-5 tests: list+paginate, inline edit, delete-without-judgments, delete-with-judgments-409-toast, metadata clear-to-null).
- DoD:
  - [ ] Idea file exists with origin pointer to this plan's §3.4.

### 3.4b Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `ui/src/app/query-sets/__tests__/*` (if present) | Placeholder card render | TBD at impl time | Update to render `<QueriesTable>`; remove `chore_query_inline_edit_delete` bareword assertion. |
| `backend/tests/integration/test_query_sets_router.py` (if exists) | Existing 4 endpoints | TBD | No change — existing routes untouched. |
| `backend/tests/contract/test_openapi_surface.py` | OpenAPI endpoint count | 1 | Update the endpoint count assertion: `41 → 44` (3 new endpoints). |
| All other test files | — | 0 | No changes — this feature is additive at every layer. |

### 3.5 Migration verification

N/A — no migrations.

### 3.6 CI gates
- [ ] `make test-unit`
- [ ] `make test-integration`
- [ ] `make test-contract`
- [ ] `cd ui && pnpm test && pnpm typecheck && pnpm lint && pnpm build`
- [ ] `bash scripts/ci/verify_enum_source_of_truth.sh` (no-op for this feature, but verifies the gate still passes)
- [ ] 80% coverage gate

---

## 4) Documentation update workstream

### 4.0 Core context files
- **`state.md`** — yes: Story 5.1 moves the backlog row to "Most recent meaningful changes" and decrements backlog count.
- **`architecture.md`** — no changes (no new layer; this feature spans existing router/repo/UI).
- **`CLAUDE.md`** — no changes.

### 4.1 Architecture docs
- [ ] `docs/01_architecture/api-conventions.md` — append the new GET endpoint to §"Pagination" MVP1-active list.

### 4.2 Product docs
- [ ] `docs/02_product/mvp1-user-stories.md` — extend US-08.

### 4.3 Runbooks
- [ ] `docs/03_runbooks/ui-debugging.md` — append "Per-query editing" section.

### 4.4 Security docs
- No changes.

### 4.5 Quality docs
- No changes (test layers unchanged).

**Documentation DoD**
- [ ] `state.md` reflects shipped feature, backlog row removed.
- [ ] api-conventions.md, mvp1-user-stories.md, ui-debugging.md merged in the same PR.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals
- None proactive. This feature is purely additive at every layer.

### 5.2 Planned refactor tasks
- [ ] Delete the placeholder card at `ui/src/app/query-sets/[id]/page.tsx:61-72` — replaced by `<QueriesTable>`. This is not a "refactor" in the lean-refactor-workstream sense; it's just the body of Story 4.1.

### 5.3 Refactor guardrails
- [ ] No behavior change to the existing 4 query-set endpoints.
- [ ] No changes to `add-queries-dialog.tsx`, `generate-judgments-dialog.tsx`, `associated-judgment-lists.tsx`, `create-query-set-modal.tsx`.
- [ ] No changes to the existing `useQuerySets` / `useQuerySet` / `useCreateQuerySet` / `useAddQueries` hooks (extensions to the same file only).

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `feat_study_lifecycle` Phase 1 + 2 | All stories | Implemented (PR #18, #25) | Blocker — no `queries` table; non-issue today. |
| `feat_llm_judgments` | Stories 3.1, 3.2 | Implemented (PR #35) | FK guard has nothing to guard against; degrades to 204-always. Non-issue today. |
| `feat_studies_ui` | Stories 4.1, 4.2, 4.3 | Implemented (PR #50) | No UI surface to attach the table to. Non-issue today. |
| Shadcn `<DropdownMenu>` primitive | (not used) | **N/A** — would add a new npm package which spec §5 forbids. Story 4.1 uses inline icon-button trio instead. | No new deps required. |
| `pnpm openapi-typescript` runnable against the running backend | Story 4.0 | Implemented (existing tooling) | Non-issue. |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| FK `IntegrityError` doesn't surface synchronously (deferred constraint) | Low | High | Postgres FK constraints are immediate by default (no `INITIALLY DEFERRED`); verified at [`judgment.py:64-67`](../../../../backend/app/db/models/judgment.py#L64-L67). Defense: `await db.flush()` in `delete_query` forces the check before the router's commit. |
| Bad `since` ISO-8601 fails outside the Pydantic guard | Low | Low | FastAPI's `datetime` query-param coercion handles ISO-8601 parsing + raises 422 on bad input — no special handling needed. |
| `pnpm openapi-typescript` fails to find the new types because the backend wasn't running | Medium | Medium | Story 4.0 prerequisite: backend stack running locally (`make up`) with the new endpoints merged. CI: backend tests run first; frontend types are committed by Story 4.0 author. |
| Race condition on DELETE → concurrent INSERT to `judgments` | Low | Low | Postgres FK check during DELETE catches this synchronously — the operator sees a 409 if the concurrent INSERT committed first, or 204 if it didn't. Locked in spec §10 Threat 4. |
| 409 envelope `judgment_lists` array exceeds reasonable response size with malicious operator | Low | Low | Hard `LIMIT 10` on the sample query. `overflow_count` is the only growable field (`int`). Response stays under 2KB. |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| FK violation on DELETE | Operator deletes a query that has judgments | 409 `QUERY_HAS_JUDGMENTS` with structured envelope; row unchanged | Operator deletes the parent judgment list, retries |
| Cursor decode failure | Stale or malformed cursor on GET | 422 `VALIDATION_ERROR`; client resets to page 1 | Auto-recovery in the frontend (toast + reset) |
| Empty `model_dump(exclude_unset=True)` on PATCH | Operator sends `{}` body | 200 with the current `QueryRow`; no DB UPDATE | n/a (intentional) |
| Postgres connection drop during DELETE | Network blip | 503 `SERVICE_UNAVAILABLE` (retryable); query state unchanged | Frontend retry via `apiClient` 4-attempt contract |
| Worker concurrent INSERT to `judgments` between operator's lookup and DELETE | Race condition | DELETE → 409 (Postgres FK check beats the worker's commit) OR DELETE → 204 (operator wins) — both deterministic | n/a |

## 7) Sequencing and parallelization

### Suggested sequence

1. **Epic 1 stories** (1.2 → 1.3 → 1.1): build the repo + helper layer first, then the router that consumes them.
2. **Epic 2 stories** (2.2 → 2.1): same pattern.
3. **Epic 3 stories** (3.2 → 3.1): same pattern.
4. **Backend coverage + contract** assertions: all 3 epics merged + tests green.
5. **Epic 4 stories** (4.0 → 4.1 → 4.2 → 4.3): frontend depends on the regenerated `lib/types.ts` from the backend OpenAPI.
6. **Epic 5** (5.1): docs sweep + state.md update + idea-file capture for the deferred E2E.

### Parallelization opportunities

- Within Epic 1, Story 1.2 and Story 1.3 are independent (different repo files); they can be implemented in parallel commits if a single developer wants to batch.
- Within Epic 4, Story 4.2 (`<EditQueryPopover>` + `<EditMetadataDialog>`) and Story 4.3 (`<DeleteQueryDialog>`) can be implemented in parallel after Story 4.0 + 4.1 merge.
- Epic 5 has no dependencies on Epic 4 component tests passing — the docs sweep can run in parallel with the frontend test cycle.

## 8) Rollout and cutover plan

- **Rollout stages:** none. Single-tenant MVP1 with no feature flag infrastructure.
- **Feature flag strategy:** none.
- **Migration/cutover steps:** none.
- **Reconciliation/repair strategy:** N/A.

## 9) Execution tracker (copy/paste section)

### Current sprint
- [ ] Story 1.2 — Repo extensions: get_query, count_queries_for_set, list_queries_for_set_cursor
- [ ] Story 1.3 — Batch judgment-count helper
- [ ] Story 1.1 — Router GET /api/v1/query-sets/{set_id}/queries
- [ ] Story 2.2 — Repo update_query + UpdateQueryRequest schema
- [ ] Story 2.1 — Router PATCH endpoint
- [ ] Story 3.2 — Repo delete_query + count_and_sample_judgment_refs
- [ ] Story 3.1 — Router DELETE endpoint + OpenAPI 409 wiring
- [ ] Story 4.0 — Frontend hooks (useQueries, useUpdateQuery, useDeleteQuery)
- [ ] Story 4.1 — <QueriesTable> replaces placeholder card
- [ ] Story 4.2 — <EditQueryPopover> + <EditMetadataDialog>
- [ ] Story 4.3 — <DeleteQueryDialog> + 409 toast with link
- [ ] Story 5.1 — Docs sweep + state.md + deferred-E2E idea file

### Blocked items
- (none currently)

### Done this sprint
- (none yet)

## 10) Story-by-Story Verification Gate

Before marking any story complete:

- [ ] Files created/modified match story scope (`New files` / `Modified files` tables)
- [ ] Endpoint contract implemented exactly as documented (method/path/body/status/error code)
- [ ] Key interfaces implemented with the documented signatures
- [ ] Required tests added/updated for all relevant layers
- [ ] Commands executed and passed: `make test-unit`, `make test-integration`, `make test-contract`, `cd ui && pnpm test && pnpm typecheck && pnpm lint && pnpm build`
- [ ] No migration round-trip needed (this feature has zero schema change)
- [ ] Related docs / placeholder-card removal completed in same PR when behavior/contract changed

## 11) Plan consistency review

| Check | Status |
|---|---|
| Spec endpoint count = plan endpoint count | 3 endpoints in spec §8.1; 3 endpoints across Stories 1.1, 2.1, 3.1. ✅ |
| Spec error codes = plan error codes | 4 codes in spec §8.5 (`QUERY_SET_NOT_FOUND` reused, `QUERY_NOT_FOUND`, `QUERY_HAS_JUDGMENTS`, `VALIDATION_ERROR`); all 4 appear in plan endpoint tables + contract test scope. ✅ |
| Spec FR coverage = plan story assignments | FR-1..FR-6 all assigned per §1 traceability table. ✅ |
| Pydantic schema field names match endpoint table fields | `QueryRow`, `QueryListResponse`, `UpdateQueryRequest`, `JudgmentListRef`, `QueryHasJudgmentsDetail`, `QueryHasJudgmentsEnvelope` all defined in §9 of spec + Stories 1.1, 2.2, 3.1. ✅ |
| DoD references correct error codes + HTTP status | Each story's DoD references the AC IDs which encode error codes + status. ✅ |
| No file is "new" in more than one story | `queries-table.tsx` only in Story 4.1; `edit-query-popover.tsx` + `edit-metadata-dialog.tsx` only in Story 4.2; `delete-query-dialog.tsx` only in Story 4.3. ✅ |
| All modified files exist | `backend/app/db/repo/query.py`, `backend/app/db/repo/judgment.py`, `backend/app/db/repo/__init__.py`, `backend/app/api/v1/query_sets.py`, `backend/app/api/v1/schemas.py`, `ui/src/lib/api/query-sets.ts`, `ui/src/app/query-sets/[id]/page.tsx`, `ui/src/lib/types.ts` — all glob-verified. ✅ |
| Test file count matches §3 inventory | 3 unit + 4 integration + 1 contract + 5 frontend = 13 test files; cross-referenced in §3 + traceability matrix. ✅ |
| Gate arithmetic | Epic 1 ends with 1 new endpoint live; Epic 2 ends with 2; Epic 3 ends with 3. Frontend epic ends with table + 3 overlays. Matches story counts. ✅ |
| Open questions resolved | Spec §19 has no open questions; running-study protection deferred. ✅ |
| Frontend UI Guidance completeness | All required subsections present in §"UI Guidance" above. ✅ |
| Enumerated value contract audit | This feature adds NO enums; verified per spec §8.4. ✅ |
| Audit-event coverage | N/A — MVP1 has no `audit_log`; spec §6 lists MVP2 emission contract. ✅ |
| Legacy behavior parity | N/A — no component >100 LOC deleted/migrated. Stated explicitly in §"Legacy behavior parity". ✅ |

---

## 12) Definition of plan done

- [x] Every FR mapped to stories/tasks/tests/docs updates (§1).
- [x] Every story includes New files, Modified files, Endpoints, Key interfaces, Tasks, DoD.
- [x] Test layers (unit / integration / contract / e2e) explicitly scoped; E2E deferred to idea file.
- [x] Documentation updates across docs/01-05 planned and owned (Story 5.1).
- [x] Lean refactor scope and guardrails explicit.
- [x] Epic gates measurable.
- [x] Story-by-Story Verification Gate included.
- [x] Plan consistency review (§11) performed with no unresolved findings.
