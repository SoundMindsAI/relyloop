# Implementation Plan — Create-Study Step 1 Target Autocomplete

**Date:** 2026-05-20
**Status:** Complete (PR [#165](https://github.com/SoundMindsAI/relyloop/pull/165), merged 2026-05-20 as squash commit `bd4516a`)
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy source(s):** [`docs/01_architecture/adapters.md`](../../../01_architecture/adapters.md), [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md), [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md), [`CLAUDE.md`](../../../../CLAUDE.md) (Absolute Rule #4 — engine-specific code only in adapters).

---

## 0) Planning principles

- Spec traceability first: every story maps to FR IDs and ACs from `feature_spec.md`.
- Backend ships before frontend (vertical-slice order — F1 hook fails fast if B2 endpoint is missing).
- F2 modal swap depends on F1 hook + B2 endpoint + B1 exception class (the four are sequenced; only the two backend stories are parallelizable).
- No new migrations, no schema changes (spec §9). Stays purely additive at the API + UI layers.
- Test layers: every new endpoint gets unit + integration + contract; every modified frontend file gets unit + at least one E2E case.

## 1) Scope traceability (FR → epics/stories)

| FR ID | Story | Notes |
|---|---|---|
| FR-1 (REST endpoint exposes `list_targets()`) | Epic 1 / Story B2 | New `GET /api/v1/clusters/{cluster_id}/targets`; thin passthrough. |
| FR-2 (adapter distinguishes 401/403 from unreachable) | Epic 1 / Story B1 | New `TargetsForbiddenError`; rewires `list_targets()` to opt out of `_request` default translation. |
| FR-3 (TanStack hook for new endpoint, with retry predicate + meta-suppress) | Epic 2 / Story F1 | New `useClusterTargets` in `ui/src/lib/api/clusters.ts`; retry predicate respects `error.retryable`. |
| FR-4 (replace `<Input>` with `<EntitySelect>` + cluster cascade resets target) | Epic 2 / Story F2 | Modal swap + extend existing `onChange` cascade. |
| FR-5 ("Enter manually" toggle + auto-engage on TARGETS_FORBIDDEN + cluster-change reset of toggle/hint) | Epic 2 / Story F2 | Toggle UI + auto-engage effect + cluster-cascade reset of toggle state bundled with the modal swap; same component touch. |
| FR-6 (silence TARGET_NOT_FOUND on `useClusterSchema` — toast + retry storm) | Epic 2 / Story F1 | Bundled with `useClusterTargets` (same file, paired pattern) — `useClusterSchema` gains the same retry predicate + `meta.suppressErrorCodes: ['TARGET_NOT_FOUND']`. |
| FR-7 (alphabetical sort by target name) | Epic 2 / Story F2 | Sort inside the hook OR in the component before passing to `<EntitySelect>`. Decided: sort in the component (closer to render; preserves hook's responsibility = "fetch only"). |

No phases — single-phase feature. No deferred phase tracking artifact needed.

## 2) Delivery structure

**Epic → Story → Tasks → DoD.** Two epics, four stories (Epic 1: B1 + B2; Epic 2: F1 + F2). Post-cycle-1 GPT-5.5 review: F1+F3 merged into one Frontend API story to avoid same-file ownership conflict and to ensure FR-6's schema-toast silence lands before F2 exposes the manual-mode `<Input>` to the existing toast storm. Stories B1+B2 are parallelizable; F1 depends on B2 (consumes its endpoint); F2 depends on F1 + B1 (consumes the hook + needs the adapter exception in flight).

### Conventions

- **Backend:** routers translate adapter exceptions via the `_err()` helper at [`clusters.py:90-95`](../../../../backend/app/api/v1/clusters.py#L90-L95) (returns `HTTPException(detail={...})` with the canonical envelope). Adapter exceptions live in [`backend/app/adapters/errors.py`](../../../../backend/app/adapters/errors.py). Pydantic response models live in [`backend/app/api/v1/schemas.py`](../../../../backend/app/api/v1/schemas.py).
- **Adapter:** all engine-specific code stays in `backend/app/adapters/elastic.py` (CLAUDE.md Absolute Rule #4). The `_request` helper at [`elastic.py:127-179`](../../../../backend/app/adapters/elastic.py#L127-L179) supports `translate_errors=False` for callers that need to map status codes themselves (precedent: `get_schema` at [`elastic.py:382-406`](../../../../backend/app/adapters/elastic.py#L382-L406)).
- **Frontend:** TanStack hooks in `ui/src/lib/api/clusters.ts`; modal in `ui/src/components/studies/create-study-modal.tsx`; shadcn `<Select>` family wrapped by the existing [`<EntitySelect>`](../../../../ui/src/components/common/entity-select.tsx) primitive.
- **Modal tests:** every modal test that exercises `<EntitySelect>` MUST use the canonical shadcn-select mock pattern at [`ui/src/__tests__/helpers/shadcn-select-mock.tsx`](../../../../ui/src/__tests__/helpers/shadcn-select-mock.tsx) via the 3-line dynamic-`import()` inside `vi.mock` pattern — already in use at [`create-study-modal.test.tsx:17-20`](../../../../ui/src/__tests__/components/studies/create-study-modal.test.tsx#L17-L20), so this story just extends the existing pattern.
- **OpenAPI surface test:** every new endpoint MUST add a row to `EXPECTED_ENDPOINTS` in [`backend/tests/contract/test_openapi_surface.py:37-71`](../../../../backend/tests/contract/test_openapi_surface.py#L37-L71) — the test fails on missing entries by design.

### AI Agent Execution Protocol (applies to every story)

0. Read `CLAUDE.md`, `architecture.md`, `state.md`, `feature_spec.md`, this plan before starting story 1.
1. Implement stories in declared order: B1 → B2 → F1 → F2 (or B1‖B2 → F1 → F2 with backend parallelization).
2. Backend stories first; run `make test-unit && make test-integration && make test-contract` after each backend story (or targeted subsets).
3. Frontend stories second; run `cd ui && pnpm test` after each.
4. E2E runs once at the end (Story F2's DoD); requires the full local stack via `make up`.
5. Update docs (§4) in the same PR.
6. Attach evidence per Story-by-Story Verification Gate (§10).

---

## Epic 1 — Backend: list_targets exposure + ACL discrimination

### Story B1 — Adapter distinguishes ACL-restricted from unreachable on `list_targets()`

**Outcome:** `ElasticAdapter.list_targets()` raises `TargetsForbiddenError` on 401/403 from `_cat/indices` and `ClusterUnreachableError` on connection failures / 5xx. The existing happy-path (200 + system-index filter) is preserved.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| `backend/app/adapters/errors.py` | Add `class TargetsForbiddenError(Exception): """Cluster denied listing call (401/403). Maps to 403 TARGETS_FORBIDDEN at the router."""`. Update module-docstring exception list. |
| `backend/app/adapters/elastic.py` | Rewrite `list_targets()` body (currently `elastic.py:354-380`) to call `_request(..., translate_errors=False)` and map status codes explicitly: 2xx → existing parse loop; 401/403 → `raise TargetsForbiddenError(...)`; 4xx other / 5xx / `httpx.HTTPError` → `raise ClusterUnreachableError(...)`. Import the new exception. |
| `backend/app/adapters/protocol.py` | Update the `list_targets()` Protocol docstring at [`protocol.py:131-133`](../../../../backend/app/adapters/protocol.py#L131-L133) to mention both possible exception types. Protocol method signature is unchanged. |

**Endpoints**

None (adapter-internal change).

**Key interfaces**

```python
# backend/app/adapters/errors.py — new
class TargetsForbiddenError(Exception):
    """Cluster denied listing call (401/403 from _cat/indices or equivalent).

    Maps to 403 TARGETS_FORBIDDEN, retryable=false at the router.
    """

# backend/app/adapters/elastic.py — rewritten list_targets()
async def list_targets(self, *, request_id: str | None = None) -> list[TargetInfo]:
    """List indices on the cluster via _cat/indices?format=json.

    System indices (names starting with .) are filtered out.

    Raises:
        TargetsForbiddenError: when the cluster returns 401 or 403 (ACL restriction).
        ClusterUnreachableError: connection failures, 5xx, or other non-2xx.
    """
    try:
        resp = await self._request(
            "GET",
            "/_cat/indices",
            params={"format": "json", "h": "index,docs.count"},
            request_id=request_id,
            translate_errors=False,  # we map statuses ourselves
        )
    except httpx.HTTPError as exc:
        # _request with translate_errors=False re-raises httpx connection-class
        # exceptions (ConnectError, RemoteProtocolError, ConnectTimeout, ReadTimeout)
        # AFTER its one internal retry — see backend/app/adapters/elastic.py:200-210.
        # Translate to ClusterUnreachableError so the router emits 503 CLUSTER_UNREACHABLE
        # instead of letting the raw httpx exception surface as 500 INTERNAL_ERROR.
        raise ClusterUnreachableError(str(exc)) from exc
    if resp.status_code in (401, 403):
        raise TargetsForbiddenError(
            f"cluster denied listing call (HTTP {resp.status_code} from /_cat/indices)"
        )
    if resp.status_code >= 400:
        raise ClusterUnreachableError(
            f"HTTP {resp.status_code} from /_cat/indices"
        )
    rows: list[dict[str, Any]] = resp.json()
    out: list[TargetInfo] = []
    for row in rows:
        name = row.get("index")
        if not name or name.startswith("."):
            continue
        doc_count_raw = row.get("docs.count")
        doc_count: int | None
        if doc_count_raw is None or doc_count_raw == "":
            doc_count = None
        else:
            doc_count = int(str(doc_count_raw))
        out.append(TargetInfo(name=name, doc_count=doc_count))
    return out
```

The `_request(..., translate_errors=False)` opt-out is identical to `get_schema`'s status-mapping pattern at [`elastic.py:382-406`](../../../../backend/app/adapters/elastic.py#L382-L406). The explicit `httpx.HTTPError` catch here is **more defensive** than `get_schema`'s pattern (which lets connection errors propagate unhandled — see [Risks](#risks) for the latent-bug note); the cleaner pattern is adopted here as the going-forward standard.

**Pydantic schemas**

None (no API surface in this story; `TargetInfo` is reused unchanged).

**Tasks**

1. Add `TargetsForbiddenError` class to `backend/app/adapters/errors.py`. Update the module docstring's exception list.
2. Rewrite `list_targets()` in `backend/app/adapters/elastic.py` per the Key interfaces snippet. Import `TargetsForbiddenError`.
3. Update Protocol docstring at `backend/app/adapters/protocol.py:131-133` to mention both raise types.
4. Add unit tests (see §3.1).
5. Run `make test-unit && make lint && make typecheck`.

**Definition of Done**

- [ ] `TargetsForbiddenError` importable from `backend.app.adapters.errors`.
- [ ] `ElasticAdapter.list_targets()` raises `TargetsForbiddenError` on HTTP 401 + on HTTP 403 (unit-tested via `respx` mock — AC-5).
- [ ] `ElasticAdapter.list_targets()` raises `ClusterUnreachableError` on HTTP 500/503 + on `httpx.ConnectError` (unit-tested — AC-5).
- [ ] Existing happy-path test (`test_elastic_schema.py:202` `targets = await adapter.list_targets()`) still passes (no regression).
- [ ] `make test-unit && make lint && make typecheck` green.

---

### Story B2 — `GET /api/v1/clusters/{cluster_id}/targets` endpoint

**Outcome:** REST endpoint exposes the adapter's `list_targets()` with the canonical error envelope. Returns `200 OK { data: TargetInfo[] }` on success; `404 CLUSTER_NOT_FOUND`, `403 TARGETS_FORBIDDEN`, `503 CLUSTER_UNREACHABLE` per spec §7.3.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/clusters.py` | Add new router handler `list_cluster_targets()` after `get_cluster_schema()` at [`clusters.py:295-315`](../../../../backend/app/api/v1/clusters.py#L295-L315). Import `TargetsForbiddenError`. Update the file's top-level docstring endpoint list. |
| `backend/app/api/v1/schemas.py` | Add `TargetListResponse(BaseModel)` (and re-export the existing `TargetInfo` from `adapters.protocol`) near the existing `ClusterListResponse` at [`schemas.py:122-127`](../../../../backend/app/api/v1/schemas.py#L122-L127). |
| `backend/tests/contract/test_openapi_surface.py` | Add `("get", "/api/v1/clusters/{cluster_id}/targets", "200")` to `EXPECTED_ENDPOINTS` at [`test_openapi_surface.py:42-48`](../../../../backend/tests/contract/test_openapi_surface.py#L42-L48). |

**Endpoints**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `GET` | `/api/v1/clusters/{cluster_id}/targets` | — | `200` `{ "data": [{ "name": str, "doc_count": int \| null }, ...] }` | `CLUSTER_NOT_FOUND` (404), `TARGETS_FORBIDDEN` (403), `CLUSTER_UNREACHABLE` (503) |

**Key interfaces**

```python
# backend/app/api/v1/clusters.py — new handler

# Existing imports already at the top of clusters.py:
#   - from backend.app.adapters.errors import (ClusterUnreachableError,
#     InvalidQueryDSLError, QueryTimeoutError, TargetNotFoundError)
#   - from backend.app.services.cluster import (..., ClusterUnreachable, ...)
# Add to the adapters.errors import:
from backend.app.adapters.errors import (
    ClusterUnreachableError,
    InvalidQueryDSLError,
    QueryTimeoutError,
    TargetNotFoundError,
    TargetsForbiddenError,  # NEW (added by this story)
)
# Add to the v1.schemas import:
from backend.app.api.v1.schemas import (
    ...,
    TargetListResponse,  # NEW (added by this story)
)
# `ClusterUnreachable` (service-layer exception, NOT the adapter one) is
# already imported from `backend.app.services.cluster` — no new import needed;
# it's re-used in the exception tuple below to match the existing get_schema
# pattern at clusters.py:309-315.

@router.get(
    "/clusters/{cluster_id}/targets",
    response_model=TargetListResponse,
    tags=["clusters"],
)
async def list_cluster_targets(
    cluster_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TargetListResponse:
    """List targets (indices/collections) on the cluster (FR-1 / AC-1).

    Filters out engine system indices (names starting with ".").
    """
    cluster = await repo.get_cluster(db, cluster_id)
    if cluster is None:
        raise _err(404, "CLUSTER_NOT_FOUND", f"cluster {cluster_id} not found", False)
    try:
        async with cluster_svc.acquire_adapter(cluster) as adapter:
            targets = await adapter.list_targets()
            return TargetListResponse(data=targets)
    except TargetsForbiddenError as exc:
        raise _err(403, "TARGETS_FORBIDDEN", str(exc), False) from exc
    except (ClusterUnreachable, ClusterUnreachableError) as exc:
        raise _err(503, "CLUSTER_UNREACHABLE", str(exc), True) from exc
```

**Pydantic schemas**

```python
# backend/app/api/v1/schemas.py — new, place near ClusterListResponse
from backend.app.adapters.protocol import TargetInfo  # re-export via this module

class TargetListResponse(BaseModel):
    """``GET /api/v1/clusters/{id}/targets`` response.

    Unpaginated by design — see feature_spec.md §7.1 "pagination shape rationale".
    `<EntitySelectListPage<T>>`'s `next_cursor` and `has_more` fields are optional,
    so the bare `data`-only shape consumes correctly.
    """

    data: list[TargetInfo]
```

**Tasks**

1. Add `TargetListResponse` to `backend/app/api/v1/schemas.py`. Import `TargetInfo` from `adapters.protocol` at module top.
2. Add `list_cluster_targets()` handler to `backend/app/api/v1/clusters.py`. Place it after `get_cluster_schema()` for visual locality. Import `TargetsForbiddenError` and `TargetListResponse`.
3. Update the file-level docstring's endpoint list at [`clusters.py:9`](../../../../backend/app/api/v1/clusters.py#L9) — add `* ``GET /api/v1/clusters/{cluster_id}/targets`` — list targets`.
4. Add the new endpoint row to `EXPECTED_ENDPOINTS` in `test_openapi_surface.py`.
5. Add integration tests (see §3.2) + contract tests (see §3.3).
6. Run `make test-integration && make test-contract && make lint && make typecheck`.

**Definition of Done**

- [ ] `GET /api/v1/clusters/{cluster_id}/targets` returns `200` with body `{"data": [...]}` against a real ES + a real OpenSearch cluster (integration test, AC-1).
- [ ] System indices (e.g., `.kibana_1`) are filtered out of the response (integration test asserts membership).
- [ ] `404` returned for missing OR soft-deleted cluster with body `{"detail": {"error_code": "CLUSTER_NOT_FOUND", "message": "cluster ... not found", "retryable": false}}` (integration + contract tests, AC-2).
- [ ] `403` returned with `TARGETS_FORBIDDEN` envelope when the adapter raises `TargetsForbiddenError` (integration test using `monkeypatch` on `acquire_adapter`, AC-3).
- [ ] `503` returned with `CLUSTER_UNREACHABLE` envelope when the adapter raises `ClusterUnreachableError` (integration test, AC-4).
- [ ] `EXPECTED_ENDPOINTS` row added; `test_openapi_surface.py` passes.
- [ ] `TargetListResponse` schema appears in OpenAPI schema and is consumed by the generated frontend types when `pnpm run gen:types` regenerates (Story F1 will exercise this).
- [ ] `make test-integration && make test-contract && make lint && make typecheck` green.

---

## Epic 2 — Frontend: hooks + modal swap + manual mode

### Story F1 — Frontend API: `useClusterTargets` (new) + `useClusterSchema` (tune)

**Outcome:** `ui/src/lib/api/clusters.ts` gains a new `useClusterTargets(clusterId)` hook (FR-3) AND `useClusterSchema` is tuned to short-circuit retries on `retryable: false` errors + suppress the global `TARGET_NOT_FOUND` toast (FR-6). Both hooks share the same `error.retryable`-based retry predicate. Merged into a single story to avoid same-file ownership conflict between FR-3 and FR-6, and to ensure FR-6's schema-toast silence lands before F2 exposes the manual-mode `<Input>` to the existing retry-storm.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| `ui/src/lib/api/clusters.ts` | (a) Add `useClusterTargets(clusterId: string)` hook + re-export `TargetSummary` type, placed after `useClusterSchema` at [`clusters.ts:94-108`](../../../../ui/src/lib/api/clusters.ts#L94-L108). (b) Modify the existing `useClusterSchema` body to add `retry` predicate + `meta: { suppressErrorCodes: ['TARGET_NOT_FOUND'] }`. (c) Add `isApiError` import from `@/lib/api-errors` (used by both hooks). |
| `ui/src/__tests__/lib/api/clusters.test.ts` (new file if absent — check via `glob` at impl time) | Unit tests for both hooks; see §3.1. |

**Endpoints**

None added; `useClusterTargets` consumes the endpoint from Story B2.

**Key interfaces**

```typescript
// ui/src/lib/api/clusters.ts — additions at top of file
import { isApiError } from '@/lib/api-errors';  // existing helper
import type { EntitySelectListPage } from '@/components/common/entity-select';

// Re-export TargetInfo from generated OpenAPI types. Source of truth:
// backend/app/adapters/protocol.py TargetInfo class.
export type TargetSummary = components['schemas']['TargetInfo'];

// Reused retry predicate — does NOT retry permanent failures
// (retryable: false). Both hooks use this to avoid the TanStack default
// retry: 3, which would fire 4 GETs on TARGETS_FORBIDDEN / TARGET_NOT_FOUND.
const retryOnRetryableError = (failureCount: number, error: unknown): boolean =>
  isApiError(error)
    ? Boolean(error.retryable) && failureCount < 3
    : failureCount < 3;

// ---- NEW hook (FR-3 + FR-5 + FR-7) ----
// Hook signature matches the spec FR-3 contract:
// UseQueryResult<EntitySelectListPage<TargetSummary>, ApiError>.
// EntitySelectListPage's next_cursor + has_more fields are optional, so the
// bare `{ data }` response shape from /api/v1/clusters/{id}/targets is a
// valid concrete instance of this type — no translation needed at runtime.
export function useClusterTargets(
  clusterId: string,
): UseQueryResult<EntitySelectListPage<TargetSummary>, ApiError> {
  return useQuery<EntitySelectListPage<TargetSummary>, ApiError>({
    queryKey: ['clusters', clusterId, 'targets'],
    enabled: Boolean(clusterId),
    queryFn: async () => {
      const { data } = await apiClient.get<EntitySelectListPage<TargetSummary>>(
        `/api/v1/clusters/${clusterId}/targets`,
      );
      return data;
    },
    retry: retryOnRetryableError,
    // FR-3: silence the global toast for ACL restrictions — FR-5's inline
    // auto-engage hint is the only user-facing signal needed.
    meta: { suppressErrorCodes: ['TARGETS_FORBIDDEN'] },
  });
}

// ---- MODIFIED existing hook (FR-6) ----
export function useClusterSchema(
  id: string,
  target: string | undefined,
): UseQueryResult<Schema, ApiError> {
  return useQuery<Schema, ApiError>({
    queryKey: ['clusters', id, 'schema', target],
    enabled: Boolean(id && target),
    queryFn: async () => {
      const { data } = await apiClient.get<Schema>(`/api/v1/clusters/${id}/schema`, {
        params: { target: target ?? '' },
      });
      return data;
    },
    // FR-6: short-circuit retries on TARGET_NOT_FOUND (retryable: false).
    // TanStack default retry: 3 would otherwise fire 4 GETs per misspelled
    // keystroke when the operator types into the manual-mode <Input>.
    retry: retryOnRetryableError,
    // FR-6: silence the global toast for misspelled target names — the
    // "{N} fields discovered" hint not-rendering is sufficient signal.
    meta: { suppressErrorCodes: ['TARGET_NOT_FOUND'] },
  });
}
```

The `EntitySelectListPage<T>` import gives the new hook a canonical typing contract (per spec FR-3) — using the primitive's type directly instead of inventing a local `ClusterTargetsResponse` ensures the consumer (`<EntitySelect query={q}>` in F2) accepts the result without a structural-compatibility leap.

**Pydantic schemas**

N/A (frontend).

**Tasks**

1. Regenerate types: `cd ui && pnpm run gen:types` (or equivalent — verify the script name in `ui/package.json`). This brings `components['schemas']['TargetInfo']` and `components['schemas']['TargetListResponse']` into `ui/src/lib/types.ts` from the backend's OpenAPI export.
2. Add the `isApiError` and `EntitySelectListPage` imports + `TargetSummary` re-export + `retryOnRetryableError` predicate to `ui/src/lib/api/clusters.ts`.
3. Add `useClusterTargets` per the Key interfaces snippet.
4. Modify `useClusterSchema` to add the `retry` and `meta` options per the snippet. No other change to the hook body.
5. Add the new test file `ui/src/__tests__/lib/api/clusters.test.ts` (or extend an existing one — `glob` first). Cover both hooks per §3.1 frontend unit list.
6. Run `cd ui && pnpm lint && pnpm typecheck && pnpm test`.

**Definition of Done**

- [ ] `useClusterTargets("c-123")` returns `EntitySelectListPage<TargetSummary>` directly from the API response (no translation layer) (AC-6).
- [ ] `useClusterTargets` `enabled: false` when `clusterId` is empty string (no GET fires; unit-tested via api-client mock call counter).
- [ ] **Mocking-layer note** (cycle-2 GPT-5.5 review #2): the retry-count assertions below mock at the `apiClient.get` layer (not msw / network), so we measure TanStack's retry-predicate behavior in isolation from the api-client's own internal 503 retry loop. If we mocked at the network layer instead, a 503 retryable=true response would compound the api-client's 4 attempts × TanStack's 4 attempts = up to 16 network calls — which is real but tests the wrong layer for this story's contract. The api-client's retry behavior is covered by `api-client.test.ts` separately.
- [ ] `useClusterTargets` on `TARGETS_FORBIDDEN` (mocked at `apiClient.get`): TanStack calls `apiClient.get` exactly once (retry predicate short-circuits); no `toast.error` (unit test mocks `toast.error` and asserts never called) (AC-13 hook-level coverage).
- [ ] `useClusterTargets` on `CLUSTER_NOT_FOUND` (mocked at `apiClient.get`): exactly one `apiClient.get` call.
- [ ] `useClusterTargets` on `CLUSTER_UNREACHABLE` (mocked at `apiClient.get`): up to 4 `apiClient.get` calls — 1 initial + 3 TanStack retries (default behavior on `retryable: true`).
- [ ] `useClusterSchema` on `TARGET_NOT_FOUND` (mocked at `apiClient.get`): exactly one call; no `toast.error` (AC-11 hook-level coverage).
- [ ] `useClusterSchema` on `CLUSTER_UNREACHABLE` (mocked at `apiClient.get`): still up to 4 calls (regression check — happy-path retry behavior preserved).
- [ ] Existing `useClusterSchema` invariance test at [`cluster-action-bar.test.tsx:204`](../../../../ui/src/__tests__/components/clusters/cluster-action-bar.test.tsx#L204) still passes (cache-key semantics unchanged).
- [ ] `cd ui && pnpm lint && pnpm typecheck && pnpm test` green.

---

### Story F2 — Modal swap: `<EntitySelect>` + "Enter manually" toggle + cascade + sort

**Outcome:** Step 1 of the create-study modal renders a target dropdown by default; operator can toggle "Enter manually" to reveal the original `<Input>`; TARGETS_FORBIDDEN auto-engages manual mode with an inline amber hint; cluster change resets target + manual-mode toggle + clears the hint; dropdown options are alphabetically sorted.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/studies/create-study-modal.tsx` | Step 1 surface rewritten per UI Guidance below. Adds: `useClusterTargets` import, `useState` for manual-mode toggle, `useEffect` for cluster-change reset (manual-mode + hint), conditional render (EntitySelect vs Input), inline TARGETS_FORBIDDEN hint, sorted options, cluster-cascade `form.setValue('target', '')`. |
| `ui/src/__tests__/components/studies/create-study-modal.test.tsx` | Extend existing tests to cover: dropdown happy path, manual-mode toggle, cluster-change cascade including manual-mode reset, TARGETS_FORBIDDEN auto-engage + hint, alphabetical sort. Uses the existing `vi.mock('@/components/ui/select', ...)` pattern already in this file at [`create-study-modal.test.tsx:17-20`](../../../../ui/src/__tests__/components/studies/create-study-modal.test.tsx#L17-L20). |
| `ui/tests/e2e/studies-create.spec.ts` | Add 1 new test case for the dropdown happy path. Uses `seedCluster()` from [`ui/tests/e2e/helpers/seed.ts:100-112`](../../../../ui/tests/e2e/helpers/seed.ts#L100-L112) plus a small extension to seed a real index. |

**Endpoints**

None added; consumes `useClusterTargets` from F1 and `useClusterSchema` (existing).

**Key interfaces**

State additions inside `CreateStudyModal`:

```tsx
// ui/src/components/studies/create-study-modal.tsx — additions after line 145

const targets = useClusterTargets(clusterId);  // FR-3 hook from Story F1
const [manualMode, setManualMode] = useState(false);

// FR-5 modal-open reset: <Dialog> (Radix) keeps the component mounted across
// open/close toggles — useState alone does NOT reset on reopen. This effect
// is the authoritative reset for AC-12.
useEffect(() => {
  if (open) {
    setManualMode(false);
  }
}, [open]);

// FR-5 auto-engage: when the targets query fails with TARGETS_FORBIDDEN,
// silently flip into manual mode so the operator can type the target.
// `open` is in the dependency list AND in the guard — without it, a cached
// TARGETS_FORBIDDEN error from a prior modal session would not re-fire
// the auto-engage on reopen (the [open] reset above would set manualMode
// back to false, and React would not re-run this effect because its other
// deps haven't changed). The combined effect: on reopen with a cached
// forbidden state, both effects run → batched updates → final state is
// manualMode = true (auto-engage wins because it runs second in source order).
useEffect(() => {
  if (
    open &&
    targets.isError &&
    targets.error?.errorCode === 'TARGETS_FORBIDDEN'
  ) {
    setManualMode(true);
  }
}, [open, targets.isError, targets.error?.errorCode]);

// FR-5 cluster-change reset: when the operator switches clusters, reset to
// dropdown mode (the new cluster may permit listing). Implemented inline in
// the cluster `<EntitySelect>`'s onChange (below) — not in an effect because
// the reset is conceptually a user-action consequence, not a derived-state
// reaction.

// FR-7 alphabetical sort: render-time, leaves the hook as fetch-only.
const sortedTargets = useMemo(() => {
  const list = targets.data?.data ?? [];
  return [...list].sort((a, b) =>
    a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }),
  );
}, [targets.data?.data]);

// Pre-build the EntitySelect query object so the sort applies upstream of the
// primitive without forcing the primitive to know about sort semantics.
const sortedTargetsQuery = {
  ...targets,
  data: targets.data ? { data: sortedTargets } : undefined,
} as typeof targets;
```

**Pydantic schemas**

N/A (frontend).

**Tasks**

1. Add `useClusterTargets` import + `TargetSummary` type import to `create-study-modal.tsx` top.
2. Add the `targets`, `manualMode`, `setManualMode`, auto-engage `useEffect`, `sortedTargets` memo, and `sortedTargetsQuery` lines after the existing `schema = useClusterSchema(...)` line at [`create-study-modal.tsx:145`](../../../../ui/src/components/studies/create-study-modal.tsx#L145).
3. Modify the cluster `<EntitySelect>` onChange at [`create-study-modal.tsx:443-448`](../../../../ui/src/components/studies/create-study-modal.tsx#L443-L448): add `form.setValue('target', '')` and `setManualMode(false)` to the cascade. **Order matters:** reset child fields BEFORE setting cluster_id is fine here because the resets don't depend on the new cluster value.
4. Replace lines 452-463 (the target field wrapper) with the new dual-render shown in UI Guidance below.
5. Add component-level tests to `create-study-modal.test.tsx` per §3.1 frontend unit list.
6. Add 1 E2E case to `studies-create.spec.ts` per §3.4.
7. Run `cd ui && pnpm lint && pnpm typecheck && pnpm test`. E2E runs in the §3.4 phase against the local stack.

**Definition of Done**

- [ ] Step 1 with no cluster yet → target field renders a disabled `<Select>` placeholder ("Pick a cluster first"); no `GET /clusters//targets` fires (component test asserts on disabled DOM + msw call counter = 0). (FR-4 disabled-empty case from cycle-1 GPT-5.5 review).
- [ ] Step 1 with a cluster picked → target field renders `<EntitySelect>` for the target by default (component test).
- [ ] "Enter manually" toggle renders below the dropdown; clicking it swaps in the `<Input>` (AC-9; component test).
- [ ] On `TARGETS_FORBIDDEN`: manual mode auto-engages; inline amber hint `"Cluster restricts index listing — enter the target name manually."` renders below the input; **no `toast.error` is called** (AC-10 + AC-13 modal-level; component test mocks `toast.error`).
- [ ] Cluster change resets `target`, `query_set_id`, `judgment_list_id`, `template_id`, AND resets `manualMode` to `false`, AND unmounts any prior TARGETS_FORBIDDEN hint (AC-8; component test).
- [ ] Dropdown options render in alphabetical order (AC-7; component test).
- [ ] Modal open/close/reopen cycle (operator-toggled): open → flip to manual mode → close (`open=false`) → reopen (`open=true`) → assert dropdown mode is engaged again (`manualMode === false`) — exercises the `useEffect([open])` reset, NOT a forced React unmount (AC-12; component test uses Radix `<Dialog>` controlled `open` prop, not conditional rendering).
- [ ] **Modal reopen with cached TARGETS_FORBIDDEN error** (cycle-2 GPT-5.5 review #3): open → pick ACL-restricted cluster → auto-engage fires → close → reopen with the same cluster still picked → assert `manualMode` is still `true` (auto-engage re-fires on `open` change because the cached `isError` + `errorCode` + the new `open` dep combine). Without this test, the open-reset effect would silently clobber the auto-engage state on reopen.
- [ ] Manual-mode TARGET_NOT_FOUND path: in manual mode, type a nonexistent target → `useClusterSchema` fires exactly one schema GET → no `toast.error` → "{N} fields discovered" hint does NOT render (AC-11 modal-level coverage; complements F1's hook-level test).
- [ ] E2E test against a real ES cluster (real-backend): seed cluster via `seedCluster()` + 2 user-facing indices via Playwright's `request.put(...)` against `http://localhost:9200/<index>` → open modal → pick cluster → assert dropdown options visible → pick `e2e-target-a` → advance through steps → submit → assert created study `target === 'e2e-target-a'` via API fetch (AC-1 + AC-6 + AC-7 end-to-end). Cleanup deletes the indices via `request.delete(...)`.
- [ ] `cd ui && pnpm lint && pnpm typecheck && pnpm test` green.

---

## UI Guidance (required — Story F2 touches frontend)

### Reference: current component structure (Step 1 only — F2 touches no other step)

[`ui/src/components/studies/create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx) — 700+ LOC total; Step 1 occupies lines 429-465 (~37 lines).

Step 1 sections in current order:
- **Lines 431-451** — Cluster `<EntitySelect>` (unchanged by F2 — only the `onChange` cascade is extended).
- **Lines 452-463** — Target `<Input>` + `<InfoTooltip>` + "{N} fields discovered" hint (REPLACED by F2).
- **Line 464** — Closing div for `step === 0`.

State variables consumed at Step 1 (lines 137-145):
- `clusterId = form.watch('cluster_id')` — already exists.
- `target = form.watch('target')` — already exists.
- `clusters = useClusters({ limit: 200 })` — already exists.
- `schema = useClusterSchema(clusterId, target || undefined)` — already exists.
- **NEW:** `targets = useClusterTargets(clusterId)` — Story F1.
- **NEW:** `[manualMode, setManualMode] = useState(false)` — F2.
- **NEW:** `sortedTargets` memo + `sortedTargetsQuery` derived — F2.

Insertion point for the new state lines: after line 145 (after `schema = useClusterSchema(...)`), before line 146 (`querySets = useQuerySets(...)`).

Insertion point for the new Step 1 target render: replacing lines 452-463.

The cluster-cascade `onChange` modification is at lines 443-448 (in-place edit).

### Analogous markup patterns

**Pattern: Step 2 Query set `<EntitySelect>` (the cleanest peer to copy)** — from [`create-study-modal.tsx:468-482`](../../../../ui/src/components/studies/create-study-modal.tsx#L468-L482):

```tsx
{/* Pattern source — Step 2 query-set picker — lines 468-482 */}
<div className="space-y-1.5">
  <Label htmlFor="cs-qs">Query set</Label>
  <EntitySelect
    id="cs-qs"
    data-testid="cs-qs"
    query={querySets}
    getId={(q) => q.id}
    getLabel={(q) => q.name}
    value={values.query_set_id || undefined}
    onChange={(v) => {
      form.setValue('query_set_id', v ?? '');
      form.setValue('judgment_list_id', '');
    }}
    placeholder="Choose a query set"
  />
</div>
```

**Pattern: Cluster `<EntitySelect>` with `getStatus`** — from [`create-study-modal.tsx:431-451`](../../../../ui/src/components/studies/create-study-modal.tsx#L431-L451) — shown above; the target dropdown does NOT use `getStatus` (per spec §4 anti-patterns — no per-target health field on `TargetInfo`).

### Target Step-1 markup (replacing lines 452-463)

```tsx
{/* Target field — F2 dual-render: dropdown OR manual <Input> */}
<div className="space-y-1.5">
  <div className="flex items-center gap-1">
    <Label htmlFor="cs-target">Target index / collection</Label>
    <InfoTooltip glossaryKey="study.target" />
  </div>

  {manualMode ? (
    // Manual-mode fallback (preserves the original Input behavior)
    <>
      <Input id="cs-target" {...form.register('target')} placeholder="products" />
      {targets.isError && targets.error?.errorCode === 'TARGETS_FORBIDDEN' && (
        <p className="text-xs text-amber-600">
          Cluster restricts index listing — enter the target name manually.
        </p>
      )}
    </>
  ) : !clusterId ? (
    // FR-4: no cluster picked yet → render a disabled placeholder Select
    // matching the EntitySelect visual idiom (Radix Select trigger, disabled).
    // The targets query is also `enabled: false` in this state (see
    // useClusterTargets's enabled guard), so no GET fires.
    <Select value="" onValueChange={() => {}} disabled>
      <SelectTrigger id="cs-target" data-testid="cs-target" disabled>
        <SelectValue placeholder="Pick a cluster first" />
      </SelectTrigger>
    </Select>
  ) : (
    // Dropdown mode (default, with a cluster picked)
    <EntitySelect
      id="cs-target"
      data-testid="cs-target"
      query={sortedTargetsQuery}
      getId={(t) => t.name}
      getLabel={(t) =>
        `${t.name} (${t.doc_count != null ? t.doc_count.toLocaleString() : '?'} docs)`
      }
      value={values.target || undefined}
      onChange={(v) => form.setValue('target', v ?? '')}
      placeholder="Choose a target"
      emptyState={{ message: 'No targets found on this cluster.' }}
    />
  )}

  {/* "Enter manually" / "Use dropdown" toggle — always visible at Step 1 */}
  <button
    type="button"
    onClick={() => setManualMode((prev) => !prev)}
    className="text-xs text-muted-foreground underline"
    aria-pressed={manualMode}
    title="Type the target name instead of picking from the cluster's index list."
  >
    {manualMode ? 'Use dropdown' : 'Enter manually'}
  </button>

  {/* "{N} fields discovered" hint — preserved verbatim from the original */}
  {schema.data && (
    <p className="text-xs text-muted-foreground">
      {schema.data.fields.length} fields discovered
    </p>
  )}
</div>
```

The empty-state with manual-mode CTA: when `targets.data?.data.length === 0`, the `<EntitySelect>`'s built-in `emptyState.message` shows `"No targets found on this cluster."`. The user can click "Enter manually" right below to flip into manual mode — no custom CTA needed because the toggle is always visible (locked decision per spec §19).

### Cluster-cascade modification (in-place edit at lines 443-448)

```tsx
{/* Cluster picker — F2 extends the existing cascade */}
<EntitySelect
  id="cs-cluster"
  data-testid="cs-cluster"
  query={clusters}
  getId={(c) => c.id}
  getLabel={(c) => `${c.name} (${c.engine_type})`}
  getStatus={(c) =>
    c.health_check.status === 'unreachable' ? 'unknown' : c.health_check.status
  }
  value={values.cluster_id || undefined}
  onChange={(v) => {
    form.setValue('cluster_id', v ?? '');
    form.setValue('target', '');           // NEW (FR-4)
    form.setValue('query_set_id', '');
    form.setValue('judgment_list_id', '');
    form.setValue('template_id', '');
    setManualMode(false);                  // NEW (FR-5 cluster-change reset)
  }}
  placeholder="Choose a cluster"
/>
```

### Layout and structure

- **Visual hierarchy unchanged.** Cluster picker (top) → Target field (below) → "{N} fields discovered" hint (small grey text below target). The toggle button sits between the picker and the hint; visually subordinate (small muted underlined text). The amber TARGETS_FORBIDDEN hint replaces the empty space the toggle would otherwise leave.
- **No responsive changes.** The modal is single-column on all viewports; existing layout is preserved.

### Interaction behavior table

| User action | Frontend behavior | API call |
|---|---|---|
| Modal opens | `manualMode = false` (initial state); cluster + target both empty | None |
| Operator picks cluster A | `cluster_id` set; `target` + `query_set_id` + `judgment_list_id` + `template_id` reset; `manualMode` reset to `false` | `useClusterTargets(A)` fires `GET /clusters/A/targets` |
| Targets returns happy | Dropdown renders sorted options | — (cached) |
| Targets returns `TARGETS_FORBIDDEN` | `manualMode` auto-flips to `true`; inline amber hint renders | — (single attempt, no retry, no toast) |
| Targets returns `CLUSTER_UNREACHABLE` | `<EntitySelect>` renders disabled trigger + "Retry" button; manual mode does NOT auto-engage | Up to 4 attempts (default retry on retryable: true) |
| Operator clicks "Enter manually" | `manualMode = true`; toggle label flips to "Use dropdown"; `<Input>` rendered | None |
| Operator types `prodd` in manual mode | Schema query fires once per debounced render; `schema.data` stays undefined; "{N} fields discovered" hint hidden; no toast (FR-6) | `GET /clusters/A/schema?target=prodd` fires once (FR-6 retry predicate) |
| Operator picks target from dropdown | `target` set to the picked target's name; `useClusterSchema` fires | `GET /clusters/A/schema?target=<picked>` |
| Operator switches to cluster B | Full cascade reset (incl. `target` and `manualMode`); dropdown re-fetches against B | `useClusterTargets(B)` fires `GET /clusters/B/targets` |

### Handler function patterns

```tsx
// useEffect — auto-engage manual mode on TARGETS_FORBIDDEN.
// `open` is in BOTH the guard AND the dependency list — without it, a cached
// TARGETS_FORBIDDEN error from a prior modal session would not re-fire the
// auto-engage on reopen because the [open]-reset effect would clobber it and
// React would not re-run this effect (its other deps haven't changed).
// See Story F2 Key interfaces for the authoritative snippet; this block is
// just the handler-pattern view of the same code.
useEffect(() => {
  if (
    open &&
    targets.isError &&
    targets.error?.errorCode === 'TARGETS_FORBIDDEN'
  ) {
    setManualMode(true);
  }
}, [open, targets.isError, targets.error?.errorCode]);

// useMemo — render-time alphabetical sort by name (case-insensitive)
const sortedTargets = useMemo(() => {
  const list = targets.data?.data ?? [];
  return [...list].sort((a, b) =>
    a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }),
  );
}, [targets.data?.data]);
```

### Information architecture placement

Unchanged. Step 1 of the create-study wizard, reached via "New study" button on `/studies`. Target field stays immediately below the cluster picker. The only new top-level interactive element is the "Enter manually" toggle button (visually subordinate, between the field and the existing "{N} fields discovered" hint).

### Tooltips and contextual help

Per spec §11:

| Element | Tooltip / help text | Trigger | Markup pattern |
|---|---|---|---|
| "Target index / collection" label | Existing `study.target` glossary entry (unchanged) | hover on `<InfoTooltip>` next to label | `<InfoTooltip glossaryKey="study.target" />` — already present at line 455, kept verbatim |
| "Enter manually" toggle | `"Type the target name instead of picking from the cluster's index list."` | hover (HTML `title` attribute) | `<button … title="…">` — see Target Step-1 markup above |
| TARGETS_FORBIDDEN inline hint | `"Cluster restricts index listing — enter the target name manually."` | always visible when manualMode + TARGETS_FORBIDDEN | `<p className="text-xs text-amber-600">…</p>` — see Target Step-1 markup |
| EntitySelect error state | Built into primitive — disabled trigger + "Retry" button | default render on error | Already in `<EntitySelect>` — no spec change |
| EntitySelect empty state | `"No targets found on this cluster."` | default render on `data.length === 0` | `emptyState={{ message: 'No targets found on this cluster.' }}` prop |

### Visual consistency table

| New element | CSS class / pattern source |
|---|---|
| Target dropdown trigger | `<EntitySelect>` primitive (Radix Select under the hood). Matches Step-2/3 dropdowns visually. |
| "Enter manually" toggle button | `text-xs text-muted-foreground underline` — matches the muted-secondary text style used elsewhere in modal hints (e.g., "{N} fields discovered" at line 459 uses `text-xs text-muted-foreground`). |
| TARGETS_FORBIDDEN amber hint | `text-xs text-amber-600` — matches existing amber hints (e.g., the auto-fill Undo toast and the `__placeholder__` warning per `chore_create_study_wizard_polish`). |
| Empty-state placeholder | Inherited from `<EntitySelect>`'s `emptyState.message` rendering (disabled trigger showing the message). |

### Component composition

Inline. F2 does NOT extract a new component for the target field. Reasons:
- The dual-render is short (<40 LOC of JSX) and doesn't repeat anywhere else.
- Extracting a `<TargetField>` component would require threading `clusterId`, `manualMode`, `setManualMode`, `targets`, `schema`, and the form register down — strictly more boilerplate than the inline version.
- Step 4 search-space builder (PR #163) sets the precedent: even larger Step-4 surface stays inline in the modal.

If we add a third surface that needs target autocomplete (e.g., a study-clone "change target" affordance per `feat_study_clone_from_previous`), extract then — not now.

### Legacy behavior parity

**No legacy behavior parity table needed** — the target field is <40 LOC of JSX being replaced (lines 452-463). It contains:
- One `<Input>` with `form.register('target')` — preserved in manual mode.
- One `<InfoTooltip>` — preserved (unchanged).
- One `{schema.data && (...)}` "{N} fields discovered" hint — preserved verbatim in both modes.

No client-side validations, loading states, disabled conditions, error handlers, optimistic updates, button-label-state changes, or confirmation dialogs exist on the current target field. The only behavioral change is the addition of dropdown mode + manual-mode toggle (both new behaviors per FR-3/4/5).

### Client-side persistence

None. `manualMode` is React state only — resets on modal close (per spec FR-5: "default to off (dropdown-mode) on every modal open. Persistence across opens is out of scope"). No `localStorage` / `sessionStorage` involved.

---

## 3) Testing workstream

### 3.1 Unit tests

**Backend unit** (`backend/tests/unit/adapters/`):

- [ ] **Story B1 — `test_elastic.py` (extend existing test module):** assert `ElasticAdapter.list_targets()` raises `TargetsForbiddenError` on HTTP 401 (mock via `respx`); raises `TargetsForbiddenError` on HTTP 403; raises `ClusterUnreachableError` on HTTP 500; raises `ClusterUnreachableError` on HTTP 503; raises `ClusterUnreachableError` on `httpx.ConnectError` (covers AC-5). Verify the happy-path test at `test_elastic_schema.py:202` still passes (no regression).
- [ ] **Story B1 — `test_protocol.py` (extend):** import `TargetsForbiddenError` from `backend.app.adapters.errors`; assert it's distinct from `ClusterUnreachableError` and `TargetNotFoundError`.

**Frontend unit** (`ui/src/__tests__/`):

- [ ] **Story F1 — `lib/api/clusters.test.ts` (new file; verify absence via `glob` at impl time, extend if present):** covers BOTH hooks (single file ownership). For `useClusterTargets`: returns `EntitySelectListPage<TargetSummary>` directly; `enabled: false` when `clusterId` is empty (no GET fires; msw call counter assertion); retry predicate fires exactly one GET on `TARGETS_FORBIDDEN` (assert `toast.error` mock never called); exactly one GET on `CLUSTER_NOT_FOUND`; up to 4 GETs on `CLUSTER_UNREACHABLE` (AC-6 + AC-13 hook-level). For `useClusterSchema`: fires exactly one GET on `TARGET_NOT_FOUND`; no `toast.error` on 404; up to 4 GETs on `CLUSTER_UNREACHABLE` (regression check) (AC-11 hook-level).
- [ ] **Story F2 — `components/studies/create-study-modal.test.tsx` (extend existing file):** target field renders disabled placeholder when no cluster picked (FR-4 disabled-empty case; component test asserts disabled DOM + 0 GETs); dropdown mode renders `<EntitySelect>` for target (`cs-target` trigger present) after a cluster is picked; manual mode renders `<Input>`; toggle flips between them; cluster change resets `target` + `manualMode`; TARGETS_FORBIDDEN auto-engages manual mode + amber hint visible; **no `toast.error` is called on TARGETS_FORBIDDEN** (mocked); alphabetical sort assertion on rendered option text; **modal open→close→reopen cycle resets `manualMode` to false** via the `useEffect([open])` reset (AC-12 — uses controlled `open` prop, NOT a forced React unmount, because Radix `<Dialog>` keeps the inner component mounted); **manual-mode TARGET_NOT_FOUND modal-level test** (operator types a nonexistent target → 1 schema GET → no toast → no "{N} fields discovered" hint) (AC-11 modal-level). Uses the existing `vi.mock('@/components/ui/select', ...)` pattern at file lines 17-20.

### 3.2 Integration tests

**Backend integration** (`backend/tests/integration/`):

- [ ] **Story B2 — `test_clusters_api.py` (extend with new `TestTargetsEndpoint` class):**
  - Case 1: against real ES (engine_type=elasticsearch) — seed 3 user-facing indices + 1 system index → `GET /api/v1/clusters/{id}/targets` returns 200 with exactly the 3 user-facing names in `data`.
  - Case 2: against real OpenSearch (engine_type=opensearch) — same as Case 1 but against the OpenSearch service container.
  - Case 3: assert the response body matches exactly `{"data": [{"name": str, "doc_count": int | None}, ...]}` with no extra keys (response-shape lock per spec §7.1).
- [ ] **Story B2 — `test_clusters_api_targets_errors.py` (new file):** using the test database + `monkeypatch` on `cluster_svc.acquire_adapter` to inject a stub adapter:
  - Case 1: missing cluster id → 404 `CLUSTER_NOT_FOUND` envelope (AC-2).
  - Case 2: soft-deleted cluster → 404 `CLUSTER_NOT_FOUND` (verify `repo.get_cluster` already excludes soft-deleted rows — see `cluster.py:127`).
  - Case 3: stub adapter raises `TargetsForbiddenError` → 403 `TARGETS_FORBIDDEN` envelope (AC-3).
  - Case 4: stub adapter raises `ClusterUnreachableError` → 503 `CLUSTER_UNREACHABLE` envelope (AC-4).

### 3.3 Contract tests

**Backend contract** (`backend/tests/contract/`):

- [ ] **Story B2 — `test_openapi_surface.py` (extend):** add `("get", "/api/v1/clusters/{cluster_id}/targets", "200")` to `EXPECTED_ENDPOINTS` at line 42-48. Existing test logic fails on missing entries (by design); adding the row is sufficient.
- [ ] **Story B2 — `test_error_codes.py` (extend):** add THREE sibling test cases for the new endpoint, mirroring the existing `test_target_not_found` at line 152-159: (a) `test_targets_cluster_not_found` — request against a missing/soft-deleted cluster → asserts `{"detail": {"error_code": "CLUSTER_NOT_FOUND", "message": ..., "retryable": false}}` envelope; (b) `test_targets_forbidden` — monkeypatch the adapter to raise `TargetsForbiddenError` → asserts `{"detail": {"error_code": "TARGETS_FORBIDDEN", ..., "retryable": false}}` envelope; (c) `test_targets_unreachable` — monkeypatch the adapter to raise `ClusterUnreachableError` → asserts `{"detail": {"error_code": "CLUSTER_UNREACHABLE", ..., "retryable": true}}` envelope. Per spec §7.5 + cycle-1 GPT-5.5 finding #1: every reused error code on a new endpoint gets a contract test, not just the newly-introduced code.
- [ ] **Story B2 — `test_clusters_api_contract.py` (extend):** add a `TargetListResponse` shape assertion against the generated OpenAPI schema (`#/components/schemas/TargetListResponse` exists; has a single `data` property of type `array` referencing `#/components/schemas/TargetInfo`).

### 3.4 E2E tests

**Frontend E2E** (`ui/tests/e2e/`):

- [ ] **Story F2 — `studies-create.spec.ts` (extend existing real-backend spec):** add 1 new case:
  1. **Setup (Playwright-native, Node — NOT Python):** call `seedCluster()` from [`ui/tests/e2e/helpers/seed.ts:100-112`](../../../../ui/tests/e2e/helpers/seed.ts#L100-L112) for cluster registration. Then create 2 ES indices using **Playwright's `request` fixture** against `http://localhost:9200` (the ES host port published by `make up`'s Docker Compose — see [`docs/03_runbooks/local-dev.md`](../../../../docs/03_runbooks/local-dev.md)):
     ```ts
     // Inside the test, with Playwright's `request` fixture from the test arg:
     const ES_HOST = process.env.ES_URL ?? 'http://localhost:9200';
     await request.put(`${ES_HOST}/e2e-target-a`, {
       data: { mappings: { properties: { title: { type: 'text' } } } },
       headers: { 'Content-Type': 'application/json' },
     });
     await request.put(`${ES_HOST}/e2e-target-b`, { /* same shape */ });
     ```
     **Authentication:** dev-mode ES has security disabled per [`docs/01_architecture/deployment.md`](../../../../docs/01_architecture/deployment.md), so no Basic auth header is needed. If the smoke lane has auth, lift `auth_kind: 'es_basic'` + `credentials_ref: 'local-es'` from `seedCluster()` to look up the basic-auth header pattern.
  2. **Navigate via `page`** (browser interactions only, no `page.route()` mocking): open `/studies` → click "New study" button → at Step 1 pick the seeded cluster from the cluster dropdown.
  3. Assert the target dropdown loads + is enabled; assert both `e2e-target-a` and `e2e-target-b` are visible options (in alphabetical order by name).
  4. Pick `e2e-target-a` → advance through Step 2 (pick query set), Step 3 (pick template), Step 4 (use auto-fill default), Step 5 (set objective + max_trials).
  5. Submit → assert the API responds 201 → fetch the created study via `request.get('/api/v1/studies/{id}')` → assert `study.target === 'e2e-target-a'`.
  6. **Cleanup:** `await request.delete(`${ES_HOST}/e2e-target-a`)` + `e2e-target-b`. Existing test-suite teardown handles cluster soft-deletion.
- [ ] **Discipline (CLAUDE.md "E2E Testing Rules"):** Real backend only; **no `page.route()` mocking** of `/api/v1/clusters/{id}/targets` or any other endpoint exercised by this test. Pattern matches existing real-backend E2E at `studies-create.spec.ts` (cluster registration + template seed). The ES seed step uses Playwright's `request` API (Node) — NOT Python `httpx` — to match the Playwright runner's actual capabilities.

### 3.5 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `ui/src/__tests__/components/studies/create-study-modal.test.tsx` | `getByLabelText('Target index / collection')` + `fireEvent.change(...)` at line 133 | 1 occurrence | **Update** in F2: the field is no longer an `<Input>` (the existing test uses `fireEvent.change` which works on a native `<input>` AND the shadcn-select mock helper renders a native `<select>` — verify the existing assertion still holds OR rewrite to use the mock helper's value selector). |
| `ui/src/__tests__/components/clusters/cluster-action-bar.test.tsx:204` | `useClusterSchema('c-1', 'products')` invariance test | 1 | **No change needed.** F1's `useClusterSchema` retry/meta tune does not affect the invariance assertion (the test asserts cache-key behavior, not retry/toast behavior). Verified at plan-internal consistency review. |
| `ui/tests/e2e/studies-create-validation.spec.ts` | Existing E2E that pre-fills target via free-text Input | TBD (audit at impl time) | If the test uses `page.getByLabel('Target index / collection').fill('products')`, that will break after F2. Update to either pick from the dropdown (`page.click('[data-testid="cs-target"]')` → click `products`) OR flip into manual mode first. |
| `backend/tests/integration/test_clusters_api.py::TestSchemaEndpoint` | Real-ES schema endpoint tests at line 340-388 | 2 cases | **No change.** Not impacted by this feature. |
| `backend/tests/contract/test_error_codes.py::test_target_not_found` | line 152-159 | 1 | **No change.** Not impacted; sibling `test_targets_forbidden` is added by Story B2. |
| `backend/tests/contract/test_openapi_surface.py::EXPECTED_ENDPOINTS` | line 42-48 | 1 list | **Update** — add 1 row per Story B2. |

### 3.5 Migration verification

N/A — no schema changes.

### 3.6 CI gates

- [ ] `make test-unit` green (backend unit + adapter tests from B1).
- [ ] `make test-integration` green (B2 endpoint tests against real ES + OpenSearch).
- [ ] `make test-contract` green (B2 OpenAPI surface + error code tests).
- [ ] `make lint && make typecheck` green.
- [ ] `cd ui && pnpm lint && pnpm typecheck && pnpm test && pnpm build` green.
- [ ] E2E target test passes against `make up` local stack.

---

## 4) Documentation update workstream

### 4.0 Core context files

**`state.md`** — update after PR merges:
- [x] Add a "2026-MM-DD — `feat_create_study_target_autocomplete` merged into `main`" entry to "Most recent meaningful changes" with PR # + squash commit.
- [ ] Active branch: revert to `main` post-merge.
- [ ] No Alembic head change (no migration).

**`architecture.md`** — no update needed (no new top-level layer, no new critical flow).

**`CLAUDE.md`** — no update needed (no new convention or env var).

### 4.1 Architecture docs (`docs/01_architecture`)

- [ ] `adapters.md` — update the `list_targets()` Protocol line in §"The Protocol" to mention both possible exception types (mirror existing `get_schema` documentation that names `TargetNotFoundError`).
- [ ] `api-conventions.md` — append `TARGETS_FORBIDDEN` (403, `retryable: false`) to the "Standard error codes" table OR a per-feature codes section (verify which table by reading the file — the convention may be to list per-feature codes in a separate subsection).
- [ ] `ui-architecture.md` — add a brief note in §"Form dropdown primitive" or a new subsection that the create-study modal's target picker uses `<EntitySelect>` with a manual-mode fallback toggle (first surface using this combo).

### 4.2 Product docs (`docs/02_product`)

- [ ] After merge, move `docs/00_overview/planned_features/feat_create_study_target_autocomplete/` → `docs/00_overview/implemented_features/<YYYY_MM_DD>_feat_create_study_target_autocomplete/` (per `/impl-execute` finalization step).

### 4.3 Runbooks — N/A
### 4.4 Security docs — N/A
### 4.5 Quality docs — N/A

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

- Eliminate the 4-retry-storm pattern on permanent failures (`TARGET_NOT_FOUND`, `TARGETS_FORBIDDEN`) by introducing a reusable `retry` predicate keyed on `error.retryable`.
- Centralize the "pick-from-cluster + manual-fallback" UI pattern as a reference for future surfaces (e.g., `feat_study_clone_from_previous`'s clone-time target picker).

### 5.2 Planned refactor tasks

- [ ] **F1 (post cycle-1 merge):** Already extracts the `retryOnRetryableError` helper at the top of `clusters.ts` for reuse by both `useClusterTargets` and `useClusterSchema` (small helper; 3-line predicate; lives at file scope, not exported).
- [ ] No backend refactor planned.

### 5.3 Refactor guardrails

- [ ] Behavioral parity proven by tests: `useClusterSchema` happy-path invariance test at `cluster-action-bar.test.tsx:204` still passes after F1's hook tune.
- [ ] Lint/typecheck remain green.
- [ ] No expansion of product scope.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `SearchAdapter.list_targets()` | Story B1, B2 | **Shipped** (`infra_adapter_elastic`, 2026-05-10) | None — verified at `elastic.py:354-380`. |
| `<EntitySelect>` primitive | Story F2 | **Shipped** (`chore_form_dropdown_primitive`, 2026-05-18) | None — verified at `entity-select.tsx`. |
| `meta.suppressErrorCodes` mechanism | Story F1 | **Shipped** (precedent: `digests.ts:20`) | None — verified at `query-provider.tsx:31`. |
| `shadcn-select-mock.tsx` helper | Story F2 (frontend tests) | **Shipped** (`chore_extract_shadcn_select_test_mock`, 2026-05-19) | None — already in use at `create-study-modal.test.tsx:17-20`. |
| `seedCluster()` E2E helper | Story F2 (E2E) | **Shipped** (`ui/tests/e2e/helpers/seed.ts:100-112`) | None. |
| Real ES service container in CI | Story B2 integration + Story F2 E2E | **Shipped** (existing `make up` stack) | None. |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `_cat/indices` returns a very large list on a tenant cluster (>1000 indices) — UI dropdown becomes unwieldy | Low | Medium | Spec §3 calls this out of scope; the inline-search inside `<SelectContent>` is deferred. If a real tenant hits this, add typeahead filter as a follow-up. |
| **Latent bug discovered:** `ElasticAdapter.get_schema()` at [`elastic.py:399-416`](../../../../backend/app/adapters/elastic.py#L399-L416) calls `_request(..., translate_errors=False)` and lets `httpx.HTTPError` propagate unhandled. On connection failure to a registered cluster, `get_cluster_schema` would surface as 500 INTERNAL_ERROR instead of 503 CLUSTER_UNREACHABLE — pre-existing, NOT introduced by this feature, but the parallel pattern in B1's `list_targets()` makes it visible. | Low (uncommon path) | Low | Out of scope for this PR — capture as `bug_get_schema_unhandled_connect_error` idea file in the same PR (per CLAUDE.md "Tangential discoveries" rule). B1's pattern is the correct fix template when the bug ships. |
| The `respx`-mocked unit tests for `list_targets()` 401/403/5xx drift from real ES behavior | Low | Low | Story B2's integration tests run against real ES + real OpenSearch (no mocks) — catches any drift between the unit-test mock contract and reality. |
| Modal test crashes under jsdom + Radix focus-trap when extending Story F2 tests | Low (was high pre-2026-05-19) | Low | F2 explicitly uses the `shadcn-select-mock.tsx` helper already wired in the existing test file. The helper is the canonical fix; documented at `ui-architecture.md` §"Modal-level testing". |
| TanStack `retry: 3` interacts with api-client's own 503 retry (1+3 attempts × TanStack's 3 = 12 total on 503 retryable=true) | Low | Low | This is pre-existing behavior, not introduced by this feature. Out of scope; could be cleaned up later by replacing one of the two retry layers, but not a blocker. |
| OpenAPI types regen doesn't pick up new `TargetListResponse` schema | Low | Low | Story F1 task #1 explicitly calls for `pnpm run gen:types` (verify the script name). If it doesn't exist, the team's existing types-regen workflow applies. |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| Cluster auth credentials missing (resolved from mounted secrets file at adapter construction) | Operator removes `./secrets/<credentials_ref>` between cluster registration and the targets call | `acquire_adapter` raises `ClusterUnreachable` (translated `CredentialsMissing`); endpoint returns 503 `CLUSTER_UNREACHABLE` | Operator restores the secrets file and retries. |
| Elasticsearch returns malformed `_cat/indices` JSON (rows missing `index` field) | Engine internal bug or partial response | `list_targets()` silently skips malformed rows (`if not name: continue`); response shape is preserved | None — graceful degrade. |
| Network partition between FastAPI and ES mid-request | TCP timeout or `httpx.ConnectError` | `_request` raises `httpx.HTTPError`; `list_targets()` catches into `ClusterUnreachableError`; endpoint returns 503 retryable=true; api-client retries up to 3 times; TanStack retries up to 3 more times (12 total) | Operator clicks `<EntitySelect>` Retry once partition resolves. |
| Stale `targets` query cache when operator adds a new index on the cluster (out-of-band) | Operator creates a new index via Kibana while the modal is open | TanStack `staleTime: 30_000` + `refetchOnWindowFocus: true` re-fetches when the modal regains focus or after 30s; new index appears on next dropdown render | Operator clicks the dropdown again after 30s OR closes/reopens the modal. |

---

## 7) Sequencing and parallelization

### Suggested sequence

1. **B1** — adapter `TargetsForbiddenError` exception class + `list_targets()` status mapping (parallelizable with B2).
2. **B2** — REST endpoint + Pydantic response model (parallelizable with B1; depends on `TargetsForbiddenError` import from B1 — if both happen in the same PR, order doesn't matter; if split, B1 first).
3. **F1** — Frontend API (both hooks: new `useClusterTargets` + tuned `useClusterSchema`). Depends on B2 endpoint being live for full E2E coverage, but the hook unit tests run against msw mocks immediately so F1 can land before B2 is wired (caveat: the new endpoint must exist in the OpenAPI schema so `pnpm run gen:types` picks up `TargetSummary`; either land B2 first OR temporarily hand-add the type until B2 lands).
4. **F2** — modal swap + manual-mode toggle + cascade + sort + E2E (depends on F1; F1 must land first because F2 imports `useClusterTargets`).

### Parallelization opportunities

- **B1 + B2** can be split across two developers OR done back-to-back by one developer in a single PR; minimal coupling beyond the `TargetsForbiddenError` import.
- **F1's two hook changes** (new `useClusterTargets` + tuned `useClusterSchema`) ship as a single story per the cycle-1 GPT-5.5 review: same file, paired retry-predicate pattern, and the schema-toast silence MUST land before F2's manual-mode `<Input>` exposes the existing toast storm.

---

## 8) Rollout and cutover plan

- **Rollout stages:** Internal-only — single-tenant MVP1 deploys ship the feature on merge; no per-customer toggle.
- **Feature flag strategy:** None.
- **Migration/cutover steps:** None (no schema change).
- **Reconciliation/repair strategy:** None (no persistent state introduced).

---

## 9) Execution tracker (copy/paste section)

### Current sprint

- [ ] Story B1 — adapter `TargetsForbiddenError` + status mapping
- [ ] Story B2 — REST endpoint `GET /api/v1/clusters/{cluster_id}/targets` + `TargetListResponse`
- [ ] Story F1 — Frontend API: `useClusterTargets` (new) + `useClusterSchema` (tune)
- [ ] Story F2 — modal swap + manual-mode toggle + cascade + sort + E2E

### Blocked items

- (None at plan time)

### Done this sprint

- (Populated as stories complete)

---

## 10) Story-by-Story Verification Gate (Agent Checklist)

Before marking any story complete, the executing engineer or agent must attach evidence for:

- [ ] Files created/modified match story scope (`New files` / `Modified files` tables).
- [ ] Endpoint contract implemented exactly as documented (B2: method, path, body, status, error codes).
- [ ] Key interfaces implemented with compatible signatures (B1 exception signature, F1's two hook signatures).
- [ ] Required tests added/updated for all four layers where applicable.
- [ ] Commands executed and passed:
  - [ ] `make test-unit`
  - [ ] `make test-integration` (or targeted subset with explanation — e.g., `pytest backend/tests/integration/test_clusters_api.py -k Targets`)
  - [ ] `make test-contract`
  - [ ] `cd ui && pnpm test` (Stories F1/F2)
  - [ ] E2E green against `make up` local stack (Story F2 only)
- [ ] Migration round-trip evidence — **N/A** (no migration).
- [ ] Related docs (§4) updated in same PR.

---

## 11) Plan consistency review (required before execution)

Performed inline during plan generation + after cycle-1 GPT-5.5 cross-model review. Findings:

1. **Spec ↔ plan endpoint count:** Spec §7.1 lists 1 new endpoint (`GET /clusters/{id}/targets`). Plan covers it in Story B2. ✓
2. **Spec ↔ plan error code coverage:** Spec §7.5 introduces 1 new code (`TARGETS_FORBIDDEN`); reuses 2 (`CLUSTER_NOT_FOUND`, `CLUSTER_UNREACHABLE`). All 3 appear in Story B2's endpoint table + DoD + §3.3 contract tests (post-cycle-1 fix: §3.3 now adds explicit `test_targets_cluster_not_found`, `test_targets_forbidden`, `test_targets_unreachable` siblings). ✓
3. **Spec ↔ plan FR coverage:** All 7 FRs from spec are in §1 traceability table; each assigned to a story (post-cycle-1: FR-6 reassigned from F3 → bundled F1). ✓
4. **Story internal consistency:** All three stories' endpoint tables (where applicable) and Pydantic schemas match. F1 owns `clusters.ts` + `clusters.test.ts` exclusively (post-cycle-1: F3 merged into F1 to resolve the same-file ownership conflict GPT-5.5 surfaced). F2 imports `useClusterTargets` from F1 — clean dependency. ✓
5. **Test file count:** §3 lists distinct test files: `test_elastic.py` (B1 unit), `test_protocol.py` (B1 unit), `test_clusters_api.py` extension (B2 integration), `test_clusters_api_targets_errors.py` (B2 integration, new), `test_openapi_surface.py` extension (B2 contract), `test_error_codes.py` extension (B2 contract, 3 cases), `test_clusters_api_contract.py` extension (B2 contract), `clusters.test.ts` (F1 unit, new), `create-study-modal.test.tsx` extension (F2 unit), `studies-create.spec.ts` extension (F2 E2E) — **10 distinct test files / changes**, each assigned to exactly one story DoD. ✓
6. **Gate arithmetic:** No epic/phase gates beyond per-story DoD; single-PR feature. ✓
7. **Open questions resolved:** Spec §19 has no open questions remaining (all 3 from idea preflight were resolved as recommended defaults during spec generation). ✓
8. **Frontend UI Guidance completeness:** Plan §"UI Guidance" includes: Insertion point ✓, Analogous markup ✓, Target Step-1 markup with no-cluster-state branch (post-cycle-1) + cluster-cascade modification (actual JSX) ✓, Layout ✓, Interaction behavior table ✓, Handler patterns including `useEffect([open])` modal-reset (post-cycle-1) ✓, IA placement ✓, Tooltips ✓, Visual consistency table ✓, Component composition ✓, Legacy behavior parity (explicit "no table needed" with rationale) ✓, Client-side persistence (explicit "React state + open-effect reset") ✓.
9. **Plan ↔ codebase verification:**
   - `clusters.py:295-315` get_cluster_schema pattern — verified.
   - `clusters.ts:94-108` useClusterSchema hook — verified.
   - `create-study-modal.tsx:443-448` cluster onChange cascade — verified.
   - `entity-select.tsx:38-42` EntitySelectListPage type — verified; F1 now imports it directly per cycle-1 finding #4.
   - `repo.get_cluster` excludes soft-deleted rows at `cluster.py:127` — verified.
   - `test_openapi_surface.py:42-48` EXPECTED_ENDPOINTS — verified.
   - `seedCluster()` E2E helper at `seed.ts:100-112` — verified.
   - Existing modal test `vi.mock` pattern at `create-study-modal.test.tsx:17-20` — verified.
   - `_request(..., translate_errors=False)` re-raises `httpx.HTTPError` after one retry at `elastic.py:200-210` — verified (drives B1's `try/except httpx.HTTPError` addition per cycle-1 finding #5).
   - `<Dialog>` (Radix) keeps the modal component mounted across `open` toggle — verified by reading `CreateStudyModal({ open, onOpenChange })` signature; drives F2's `useEffect([open])` reset per cycle-1 finding #6.
   - `ClusterUnreachable` (service-layer) already imported at `clusters.py:65-71` — verified per cycle-1 finding #7.
10. **Infrastructure paths:** Backend module paths (`adapters/elastic.py`, `adapters/errors.py`, `adapters/protocol.py`, `api/v1/clusters.py`, `api/v1/schemas.py`) — all verified by `Read` during plan generation. No migration paths.
11. **Frontend data plumbing:** F2 adds `useClusterTargets(clusterId)` consumed by `<EntitySelect>` — `clusterId` already exists at line 137 (`form.watch('cluster_id')`). No new prop threading needed. ✓
12. **Persistence scope:** F2 uses React state only (`useState`) + an `useEffect([open])` reset to handle Radix's mounted-across-close behavior. No `localStorage`/`sessionStorage`. Spec FR-5 + plan UI Guidance both state "none for persistence; `useState` + open-effect for in-modal state." ✓
13. **Enumerated value contract audit:** This feature has NO new filter dropdowns, sort keys, status badges, or wire-value enums. The new error code `TARGETS_FORBIDDEN` is backend→frontend (not frontend→backend) and not enumerated in any frontend `<select>`. Spec §7.4 documents this explicitly. ✓
14. **Audit-event coverage:** N/A — MVP1, no audit_log yet; pure read-path endpoint.
15. **Admin control + ceiling enforcement:** N/A — MVP1, no admin model.

No unresolved findings post-cycle-1.

---

## 12) Definition of plan done

- [x] Every FR is mapped to stories/tasks/tests/docs updates.
- [x] Every story includes New files, Modified files, Endpoints, Key interfaces, Tasks, and DoD.
- [x] Test layers (unit/integration/contract/e2e) explicitly scoped per story.
- [x] Documentation updates across docs/01-05 planned (only docs/01 has updates — `adapters.md`, `api-conventions.md`, `ui-architecture.md`).
- [x] Lean refactor scope explicit (mostly N/A; one optional helper extraction noted).
- [x] Phase/epic gates measurable (per-story DoD; no separate epic gates — single PR scope).
- [x] Story-by-Story Verification Gate included.
- [x] Plan consistency review (§11) performed with no unresolved findings.
