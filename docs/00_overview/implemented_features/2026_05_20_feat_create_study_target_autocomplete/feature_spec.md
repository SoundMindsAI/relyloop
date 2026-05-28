# Feature Specification — Create-Study Step 1 Target Autocomplete

**Date:** 2026-05-20
**Status:** Draft
**Owners:** soundminds.ai (product + engineering)
**Related docs:**
- [`idea.md`](idea.md) — input brief
- [`docs/01_architecture/adapters.md`](../../../01_architecture/adapters.md) — SearchAdapter Protocol
- [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md) — `<EntitySelect>` form primitive
- [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md) — error envelope + URL structure
- [`docs/00_overview/implemented_features/2026_05_10_infra_adapter_elastic/feature_spec.md`](../../../00_overview/implemented_features/2026_05_10_infra_adapter_elastic/feature_spec.md) — origin of `SearchAdapter.list_targets()`

---

## 1) Purpose

- **Problem:** Step 1 of the create-study modal forces the operator to type the target index/collection name from memory into a free-text `<Input>`. They have no in-product discovery (must bounce out to Kibana / OpenSearch Dashboards / `_cat/indices`); typos surface as 4 console 404s + a global error toast on every misspelled keystroke; and changing clusters leaves the previous target text stale, immediately 404'ing on the new cluster.
- **Outcome:** Operator selects a cluster → an autocomplete dropdown lists the user-visible targets on that cluster (name + doc count), pre-sorted alphabetically. Typos become impossible in the dropdown path; the "Enter manually" toggle preserves the current free-text behavior for ACL-restricted clusters; changing clusters resets the target.
- **Non-goal:** Per-target health visualization (green/yellow/red); cross-cluster target search; persisting the operator's manual-mode preference between modal opens; pagination of the target list (out of scope — see §3 Out of scope).

## 2) Current state audit

### Existing implementations

| Surface | File | Behavior today |
|---|---|---|
| Step 1 target field | [`ui/src/components/studies/create-study-modal.tsx:452-462`](../../../../ui/src/components/studies/create-study-modal.tsx#L452-L462) | Free-text `<Input id="cs-target">` with placeholder `"products"`. No validation. Inline hint "{N} fields discovered" renders only if `schema.data` is populated (silently empty on 404). |
| Schema lookup hook | [`ui/src/lib/api/clusters.ts:94-108`](../../../../ui/src/lib/api/clusters.ts#L94-L108) | `useClusterSchema(id, target)`. `enabled: Boolean(id && target)`. Throws on 404 → TanStack default `retry: 3` fires 4 GET attempts → `QueryCache.onError` ([providers/query-provider.tsx:31](../../../../ui/src/components/providers/query-provider.tsx#L31)) triggers a global `toast.error("target 'xyz' not found")`. No `meta.suppressErrorCodes`. |
| Cluster-change cascade | [`ui/src/components/studies/create-study-modal.tsx:443-448`](../../../../ui/src/components/studies/create-study-modal.tsx#L443-L448) | Resets `query_set_id`, `judgment_list_id`, `template_id`. **Does NOT reset `target`** — stale target survives a cluster change and 404s immediately on the new cluster. |
| Adapter listing method | [`backend/app/adapters/elastic.py:354-380`](../../../../backend/app/adapters/elastic.py#L354-L380) | `list_targets()` calls `GET /_cat/indices?format=json&h=index,docs.count`, filters out system indices (names starting with `.`), returns `list[TargetInfo]{ name, doc_count }`. **Already shipped by `infra_adapter_elastic`; never exposed via REST.** |
| Adapter Protocol surface | [`backend/app/adapters/protocol.py:67-71, 131-133`](../../../../backend/app/adapters/protocol.py#L67-L133) | `TargetInfo(name, doc_count)` Pydantic model + `SearchAdapter.list_targets()` Protocol method, both shipped. |
| Adapter error translation | [`backend/app/adapters/elastic.py:127-173`](../../../../backend/app/adapters/elastic.py#L127-L173) | `_request(..., translate_errors=True)` (default) raises `ClusterUnreachableError` for **both** connection failures + 401/403 **and** 5xx. ACL-restricted clusters are not distinguishable from down clusters at the adapter layer today. |
| Stub adapter (integration tests) | [`backend/tests/integration/fixtures/stub_adapter.py:57-58`](../../../../backend/tests/integration/fixtures/stub_adapter.py#L57-L58) | Returns `[TargetInfo(name="stub-index", doc_count=100)]`. Suitable for integration tests of the new endpoint without a real ES cluster. |
| Cluster registration flow | [`backend/app/api/v1/clusters.py:295-315`](../../../../backend/app/api/v1/clusters.py#L295-L315) | Pattern for the new endpoint: `get_cluster` → `acquire_adapter` async context → adapter call → translate adapter exceptions to `HTTPException(detail={...})` envelope. New endpoint follows this template. |
| `<EntitySelect>` primitive | [`ui/src/components/common/entity-select.tsx`](../../../../ui/src/components/common/entity-select.tsx) | Generic form-side FK picker. Consumes `UseQueryResult<EntitySelectListPage<T>>` where the page is `{ data: T[], next_cursor?: string \| null, has_more?: boolean }`. Has built-in `isLoading` / `isError` / empty-state slots, retry button on error, optional `getStatus` health dot. Used at Steps 1 (cluster), 2 (query set + judgment list), and 3 (template). |
| Glossary tooltip key | [`ui/src/lib/glossary.ts:43-47`](../../../../ui/src/lib/glossary.ts#L43-L47) | `study.target` exists. `<InfoTooltip glossaryKey="study.target" />` already rendered at [create-study-modal.tsx:455](../../../../ui/src/components/studies/create-study-modal.tsx#L455). No change required. |

### Navigation and link impact

None. The create-study modal is reached from a button on `/studies`; no URL changes, no new routes.

| Source file | Current link target | New link target |
|---|---|---|
| — | — | — |

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| [`ui/src/__tests__/components/studies/create-study-modal.test.tsx`](../../../../ui/src/__tests__/components/studies/create-study-modal.test.tsx) | `Input` / `getByLabelText('Target index / collection')` | TBD (grep at impl time) | Update tests touching the target field to assert against `<EntitySelect>` mock instead of `<Input>`; add manual-toggle case. |
| [`ui/src/__tests__/components/clusters/cluster-action-bar.test.tsx:204`](../../../../ui/src/__tests__/components/clusters/cluster-action-bar.test.tsx#L204) | `useClusterSchema('c-1', 'products')` invariance test | 1 | No change required — invariance test asserts that deleting a cluster removes its schema query from cache; not affected by `meta.suppressErrorCodes` addition. |
| [`backend/tests/contract/test_openapi_surface.py:42-48`](../../../../backend/tests/contract/test_openapi_surface.py#L42-L48) | `EXPECTED_ENDPOINTS` list | 1 | Add `("get", "/api/v1/clusters/{cluster_id}/targets", "200")` entry. Test fails on missing entries by design. |
| [`backend/tests/contract/test_error_codes.py:152-159`](../../../../backend/tests/contract/test_error_codes.py#L152-L159) | `TARGET_NOT_FOUND` envelope assertion | 1 | No change. New error code `TARGETS_FORBIDDEN` adds a sibling test. |
| [`backend/tests/integration/test_clusters_api.py` `TestSchemaEndpoint`](../../../../backend/tests/integration/test_clusters_api.py) | Real-ES schema endpoint tests | 2 | No change. New `TestTargetsEndpoint` class adds 2 cases (happy path + system-index filter). |
| `ui/tests/e2e/studies-create.spec.ts` | Real-backend create-study flow | TBD | Add 1 e2e case: pick a target from the dropdown → submit study → confirm `study.target` persists. |

### Existing behaviors affected by scope change

| Behavior | Current | New | Decision needed |
|---|---|---|---|
| Operator types a non-existent target | 4 console 404s + global error toast every keystroke; no inline hint; Next stays enabled. | Dropdown lists real targets only (default path); fallback `<Input>` (manual mode) silences the toast (FR-6) and the operator can still attempt to type a target — schema still 404s in the network log but no toast or Next-blocking. | No (locked: FR-6 + FR-3/4). |
| Cluster change with prior target text | Target text persists; schema query immediately 404s on new cluster. | Cluster change resets the target field to empty AND resets manual-mode toggle to dropdown-mode. | No (locked: FR-4). |
| ACL-restricted cluster (security plugin present) | `list_targets()` call raises `ClusterUnreachableError` → router would translate to `CLUSTER_UNREACHABLE` (503, retryable=true) — wrong, since retry won't help. | New `TargetsForbiddenError` (adapter) → `TARGETS_FORBIDDEN` (403, retryable=false) → frontend auto-engages manual mode + shows inline hint "Cluster restricts index listing — enter target manually." | No (locked: FR-2 + FR-5). |
| `useClusterSchema` 404 toast spam | Global `toast.error("target 'xyz' not found")` per misspelled lookup. | `meta.suppressErrorCodes: ['TARGET_NOT_FOUND']` on `useClusterSchema` silences the toast. "{N} fields discovered" hint already discriminates success/failure for the manual-mode operator. | No (locked: FR-6, bundled from idea). |

---

## 3) Scope

### In scope

- (FR-1) New backend endpoint `GET /api/v1/clusters/{cluster_id}/targets`.
- (FR-2) New `TargetsForbiddenError` exception class in `backend/app/adapters/errors.py`; `ElasticAdapter.list_targets()` raises it on 401/403 (matches `get_schema`'s 404 → `TargetNotFoundError` pattern).
- (FR-3) New TanStack hook `useClusterTargets(clusterId)` returning `EntitySelectListPage<TargetSummary>` shape.
- (FR-4) Replace `<Input id="cs-target">` with `<EntitySelect>`; add `target` to the cluster-change cascade reset.
- (FR-5) "Enter manually" toggle + auto-engage on `TARGETS_FORBIDDEN`.
- (FR-6) Bundle `meta.suppressErrorCodes: ['TARGET_NOT_FOUND']` on `useClusterSchema`.
- (FR-7) Alphabetical sort by `name`.

### Out of scope

- Per-target health visualization (green/yellow/red). Would require extending `TargetInfo` with a `health` field + Protocol change + 3 test-file updates; defer until real users ask. ES single-node dev clusters report "yellow" on every index (replica unassigned) — noisy by default.
- Cursor pagination of the target list. MVP1 deployments are single-tenant Compose stacks with bounded target counts; precedent set by `GET /clusters/{id}/schema` (unpaginated sub-resource lookup) holds. Add pagination if a tenant ever runs more than 200 targets on one cluster (none has).
- Persisting the operator's manual-mode preference across modal opens (locked: always-reset on open).
- Caching the target list beyond the default TanStack 30s `staleTime`. The list is cheap and short; revalidation on focus is the expected behavior.
- Search-within-dropdown (typeahead filter inside the dropdown). Shadcn `<SelectContent>` doesn't ship with a search input; bounded target counts (<200) make this unnecessary. Defer until a tenant reports it.
- Webhook-driven invalidation of the target list when an operator adds/removes indices on the cluster. The dropdown re-fetches on modal open and on `refetchOnWindowFocus` (30s staleTime default).

### API convention check

- **Endpoint prefix:** `/api/v1/clusters/{cluster_id}/targets` — follows the existing sub-resource pattern at [`clusters.py:295`](../../../../backend/app/api/v1/clusters.py#L295) (`/clusters/{cluster_id}/schema`). Verified in `backend/app/api/v1/`.
- **Router file:** `backend/app/api/v1/clusters.py` (existing).
- **HTTP method:** `GET` (idempotent read).
- **Non-auth error envelope:** `{ "detail": { "error_code": "<CODE>", "message": "<human>", "retryable": <bool> } }` per [`api-conventions.md`](../../../01_architecture/api-conventions.md). Verified via existing handlers in [`clusters.py:307-315`](../../../../backend/app/api/v1/clusters.py#L307-L315).
- **Auth error shape:** N/A — RelyLoop MVP1 is unauthenticated single-tenant per [`tech-stack.md` §"Canonical release matrix"](../../../01_architecture/tech-stack.md).
- **Pagination:** Unpaginated (matches precedent — `/clusters/{id}/schema` is a sub-resource lookup, not a queryable list). See §3 Out of scope rationale.

### Phase boundaries (single-phase feature)

- **Phase 1 (only phase):** All FR-1 through FR-7 ship together. No deferred phase — the feature is bounded and a partial rollout has no operator value.

---

## 4) Product principles and constraints

- **Adapter Protocol vocabulary is canonical.** Method names, endpoint paths, hook names, and wire fields use `targets` (matching `SearchAdapter.list_targets()`, `TargetInfo`, the `?target=` query param on `/schema`, and the `studies.target` column). The user-visible label stays "Target index / collection" — that's UX terminology, not a wire contract.
- **No engine-specific code outside the adapter** (CLAUDE.md Absolute Rule #4). The new router endpoint dispatches through the existing `SearchAdapter` Protocol; the new `TargetsForbiddenError` is raised inside `ElasticAdapter.list_targets()` only.
- **Error envelope is the canonical shape** (CLAUDE.md / api-conventions.md). Every error response uses `{ "detail": { "error_code", "message", "retryable" } }`. Never invent per-endpoint shapes.
- **Spec ends at the modal.** This feature does NOT change study persistence, the study state machine, or any downstream worker. `studies.target` is still a free-text VARCHAR column; the only difference is that the operator picks the value from a dropdown instead of typing it.

### Anti-patterns

- **Do not** name the adapter method or endpoint `list_indexes` / `/indexes`. The Protocol uses `list_targets`; "target" is the cross-engine unified vocab (Fusion = collection, Solr = core). Vocabulary drift across the wire is a maintenance burden.
- **Do not** add a per-target `health` field to `TargetInfo`. Locked out of scope (§3). Extending the Protocol triggers parallel updates in 3 test files and adds an `_cat/indices?h=health,index,docs.count` query — for a value that's noisy in dev (yellow everywhere) and rarely actionable.
- **Do not** swallow 401/403 from `_cat/indices` as `ClusterUnreachable`. The two failures have different remediations (unreachable → retry; forbidden → manual mode). Conflating them produces wrong UX (the frontend retries 3 times on what is a permanent permission failure).
- **Do not** retry `TARGETS_FORBIDDEN` via the api-client's 503 retry path. The new error code is 403, `retryable: false`. The api-client only retries 503+retryable=true.
- **Do not** persist the manual-mode toggle in `localStorage`. Modal is short-lived; toggle should reset on each open (locked decision). Stale toggle state confuses operators who switched clusters since the last session.
- **Do not** add a separate "Refresh targets" button on the dropdown. The `<EntitySelect>` primitive already exposes its Retry button on the error state; default `staleTime: 30_000` + `refetchOnWindowFocus: true` covers the freshness path.
- **Do not** add `target` to the `<EntitySelect>`'s `getStatus` slot. The slot is for health colors; `TargetInfo` has no health field (locked anti-pattern above).
- **Do not** treat the target picker as a primary cluster-change dependency. The cascade order is: `cluster_id` changes → reset `target` + `query_set_id` + `judgment_list_id` + `template_id`. Resetting the cascade in any other order can leave dependents (query set filtered by cluster) inconsistent.

## 5) Assumptions and dependencies

- **Dependency:** `SearchAdapter.list_targets()` (already shipped by `infra_adapter_elastic`).
  - **Why required:** the new REST endpoint is a thin passthrough; it does not implement the engine call itself.
  - **Status:** Implemented for ES + OpenSearch in [`backend/app/adapters/elastic.py:354-380`](../../../../backend/app/adapters/elastic.py#L354-L380); stub implementation in [`backend/tests/integration/fixtures/stub_adapter.py:57-58`](../../../../backend/tests/integration/fixtures/stub_adapter.py#L57-L58).
  - **Risk if missing:** zero — the dependency has shipped.
- **Dependency:** `<EntitySelect>` primitive (`chore_form_dropdown_primitive`, 2026-05-18).
  - **Why required:** the new UI uses it as the dropdown widget; the primitive provides loading / error / empty states, retry, and the canonical shadcn `<Select>` rendering for form modals.
  - **Status:** Implemented at [`ui/src/components/common/entity-select.tsx`](../../../../ui/src/components/common/entity-select.tsx).
  - **Risk if missing:** zero.
- **Dependency:** `QueryProvider`'s `meta.suppressErrorCodes` mechanism.
  - **Why required:** FR-6 silences the `TARGET_NOT_FOUND` global toast on `useClusterSchema` when the operator types into the manual-mode `<Input>`.
  - **Status:** Implemented at [`ui/src/components/providers/query-provider.tsx:31`](../../../../ui/src/components/providers/query-provider.tsx#L31); precedent at [`ui/src/lib/api/digests.ts:20`](../../../../ui/src/lib/api/digests.ts#L20) for `DIGEST_NOT_READY`.
  - **Risk if missing:** zero.

No external services or cross-team dependencies. No new infra.

## 6) Actors and roles

- **Primary actor:** Relevance Engineer (per umbrella spec §6) using the create-study modal at `/studies`.
- **Role model:** N/A — RelyLoop MVP1 is single-tenant + no auth per [`tech-stack.md` §"Canonical release matrix"](../../../01_architecture/tech-stack.md).
- **Permission boundaries:** N/A.

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — `audit_log` lands at MVP2. This feature is a pure read-path enhancement with no state mutation; even at MVP2+ it would not emit audit events.

## 7) Functional requirements

### FR-1: REST endpoint exposes the adapter's `list_targets()`

- Requirement:
  - The system **MUST** expose `GET /api/v1/clusters/{cluster_id}/targets` returning `200 OK` with body `{ "data": [TargetInfo, ...] }` (see §7.1 for the pagination shape rationale — no `next_cursor` or `has_more` fields).
  - The system **MUST** return `404 CLUSTER_NOT_FOUND` if the cluster does not exist or is soft-deleted (`deleted_at IS NOT NULL`).
  - The system **MUST** return `403 TARGETS_FORBIDDEN` (`retryable: false`) when the engine refuses the listing call due to access control (typically Elasticsearch security plugin in production deployments).
  - The system **MUST** return `503 CLUSTER_UNREACHABLE` (`retryable: true`) when the engine is unreachable (connection refused, timeout, 5xx response).
  - The system **MUST** filter out system indices (names starting with `.`) — already enforced inside `list_targets()`.
- Notes: The endpoint is a thin wrapper over `acquire_adapter(cluster).list_targets()`, mirroring [`get_cluster_schema` at clusters.py:295-315](../../../../backend/app/api/v1/clusters.py#L295-L315). No new ORM models, no new DB writes.

### FR-2: Adapter distinguishes ACL-restricted from unreachable

- Requirement:
  - The system **MUST** introduce a `TargetsForbiddenError` exception in `backend/app/adapters/errors.py` (sibling to the existing `TargetNotFoundError`).
  - `ElasticAdapter.list_targets()` **MUST** raise `TargetsForbiddenError` on `_cat/indices` HTTP 401 or 403, and `ClusterUnreachableError` on connection failures or 5xx (existing behavior preserved).
  - The implementation **MUST** opt out of `_request`'s default `translate_errors=True` (it conflates 401/403/5xx) — instead call with `translate_errors=False` and map status codes explicitly, mirroring the `get_schema` pattern at [`elastic.py:382-406`](../../../../backend/app/adapters/elastic.py#L382-L406).
- Notes: The Protocol method signature (`async def list_targets(self, *, request_id: str | None = None) -> list[TargetInfo]`) does not change. The Protocol's docstring is updated to mention both possible exception types.

### FR-3: TanStack hook for the new endpoint

- Requirement:
  - The system **MUST** export `useClusterTargets(clusterId: string)` from `ui/src/lib/api/clusters.ts`.
  - The hook **MUST** return `UseQueryResult<EntitySelectListPage<TargetSummary>, ApiError>` where `TargetSummary = components['schemas']['TargetInfo']` re-exported from generated OpenAPI types.
  - The hook **MUST** set `enabled: Boolean(clusterId)` so a Select dropdown without a cluster doesn't fire a GET.
  - The hook **MUST** consume the backend's `{ data: TargetInfo[] }` response shape directly (the optional `next_cursor`/`has_more` fields on `EntitySelectListPage<T>` are absent on this endpoint — see §7.1 pagination shape rationale).
  - The hook **MUST** set a `retry` predicate that does NOT retry permanent failures: `retry: (failureCount, error) => isApiError(error) ? Boolean(error.retryable) && failureCount < 3 : failureCount < 3`. This means `CLUSTER_NOT_FOUND` (404, `retryable: false`) and `TARGETS_FORBIDDEN` (403, `retryable: false`) fire exactly one network request; `CLUSTER_UNREACHABLE` (503, `retryable: true`) and raw network failures get the default 3 retries.
  - The hook **MUST** set `meta: { suppressErrorCodes: ['TARGETS_FORBIDDEN'] }` so the global `QueryCache.onError` toast does NOT fire on ACL-restricted clusters — the inline auto-engage hint from FR-5 is the user's signal, and a duplicate toast would be noise.
- Notes: Pattern mirrors `useClusterSchema` at [`clusters.ts:94-108`](../../../../ui/src/lib/api/clusters.ts#L94-L108) but tightens retry behavior. Without the `retry` predicate, the new hook would inherit TanStack's default `retry: 3` and fire 4 GETs against ACL-restricted clusters for what is a permanent permission failure.

### FR-4: Replace Step-1 target `<Input>` with `<EntitySelect>` and reset on cluster change

- Requirement:
  - The system **MUST** replace `<Input id="cs-target">` at [`create-study-modal.tsx:457`](../../../../ui/src/components/studies/create-study-modal.tsx#L457) with an `<EntitySelect>` consuming `useClusterTargets(clusterId)`.
  - The `<EntitySelect>` **MUST** use `getLabel(t)` = `"${t.name} (${t.doc_count?.toLocaleString() ?? '?'} docs)"` so the operator sees the document count without an extra column.
  - The `<EntitySelect>` **MUST** use `getId(t)` = `t.name` (target names are unique on a cluster; ES `_cat/indices` does not return a separate identifier).
  - The cluster-change cascade at [`create-study-modal.tsx:443-448`](../../../../ui/src/components/studies/create-study-modal.tsx#L443-L448) **MUST** add `form.setValue('target', '')` to the existing resets (`query_set_id`, `judgment_list_id`, `template_id`).
  - The `<EntitySelect>` **MUST** be disabled (rendered with `loading` placeholder) when `clusterId` is empty.
  - The "{N} fields discovered" hint at [`create-study-modal.tsx:458-462`](../../../../ui/src/components/studies/create-study-modal.tsx#L458-L462) **MUST** remain (unchanged) — it confirms the target's schema is accessible regardless of how the operator picked the target.
- Notes: `<EntitySelect>` already handles loading / error / empty states + a Retry button on error. No new error UI is needed for dropdown-mode failures.

### FR-5: "Enter manually" toggle (manual mode) with auto-engage on TARGETS_FORBIDDEN

- Requirement:
  - The system **MUST** render an "Enter manually" toggle (visually subordinate — small text button or checkbox) below the `<EntitySelect>`.
  - When the toggle is on, the original `<Input id="cs-target">` **MUST** be rendered in place of the `<EntitySelect>` (full keyboard typing path preserved).
  - The toggle state **MUST** default to off (dropdown-mode) on every modal open. Persistence across opens is out of scope (§3).
  - The toggle state **MUST** also reset to off (dropdown-mode) on every cluster change, AND any inline `TARGETS_FORBIDDEN` hint **MUST** be cleared at the same time. This is the same cascade as the FR-4 `target` reset and ensures: (a) after auto-engaging manual mode on an ACL-restricted cluster A, switching to a permissive cluster B re-engages the dropdown on its own; (b) the dropdown discovery UX is the default for every new cluster.
  - When `useClusterTargets` returns an `ApiError` with `errorCode === 'TARGETS_FORBIDDEN'`, the system **MUST** auto-engage manual mode AND surface an inline amber hint `"Cluster restricts index listing — enter the target name manually."` below the `<Input>`.
  - When `useClusterTargets` returns any other error (`CLUSTER_NOT_FOUND`, `CLUSTER_UNREACHABLE`, network failure), the system **MUST** rely on `<EntitySelect>`'s built-in error state (renders a disabled trigger + Retry button) — manual mode does NOT auto-engage in these cases.
- Notes: The TARGETS_FORBIDDEN auto-engage is the UX-distinct payoff for FR-2's effort; without it, the operator gets an unactionable error toast. The cluster-change reset is the inverse — ACL-restricted-cluster experience should not infect the next cluster the operator picks.

### FR-6: Silence `TARGET_NOT_FOUND` noise on `useClusterSchema` (toast + retry storm)

- Requirement:
  - `useClusterSchema` at [`clusters.ts:94`](../../../../ui/src/lib/api/clusters.ts#L94) **MUST** be updated to pass `meta: { suppressErrorCodes: ['TARGET_NOT_FOUND'] }` so the global `QueryCache.onError` toast does not fire on 404.
  - The same `useQuery` call **MUST** set a `retry` predicate matching FR-3 (`retry: (failureCount, error) => isApiError(error) ? Boolean(error.retryable) && failureCount < 3 : failureCount < 3`) so a misspelled target fires exactly one schema GET instead of 4. `TARGET_NOT_FOUND` is `retryable: false`, so the predicate short-circuits immediately.
- Notes: Bundled from the idea's Option B mitigation, expanded after the cycle-1 GPT-5.5 review surfaced that the toast-suppress alone leaves the 3-retry storm intact. Without the retry tune, every misspelled keystroke in manual mode still fires 4 network requests against `/schema`, which floods the dev network panel and burns engine cycles on a misspell — even though the toast is silent. The "{N} fields discovered" hint silently not-rendering is sufficient signal that the target name is wrong.

### FR-7: Alphabetical sort by target name

- Requirement:
  - The `<EntitySelect>`'s rendered option order **MUST** be alphabetical (case-insensitive ascending) by `name`.
  - Sort **MUST** happen frontend-side inside the hook or component (not relying on `_cat/indices` order, which is engine-defined).
- Notes: `_cat/indices` typically returns indices in creation order; alphabetical is the canonical "find what I'm looking for" sort for a bounded list. Doc count is shown in the label but does not influence order.

## 8) API and data contract baseline

### 7.1 Endpoint surface

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `GET` | `/api/v1/clusters/{cluster_id}/targets` | List targets (indices/collections) on the cluster, filtered to user-facing names. | `CLUSTER_NOT_FOUND` (404), `TARGETS_FORBIDDEN` (403), `CLUSTER_UNREACHABLE` (503) |

Path parameter: `cluster_id` is the registered cluster's UUIDv7 (matches existing `/clusters/{cluster_id}/schema`).

Query parameters: none.

Response body (Pydantic): `TargetListResponse` with one field:
- `data: list[TargetInfo]` — list of `{ name: str, doc_count: int | None }` (existing `TargetInfo` from [`backend/app/adapters/protocol.py:67-71`](../../../../backend/app/adapters/protocol.py#L67-L71); re-exposed via API).

> **Pagination shape rationale (resolved 2026-05-20 cycle-1 GPT-5.5 review):** Earlier drafts returned `{ data, next_cursor: null, has_more: false }` to match `EntitySelectListPage<T>`. Both `next_cursor` and `has_more` are optional on `EntitySelectListPage<T>` ([`entity-select.tsx:38-42`](../../../../ui/src/components/common/entity-select.tsx#L38-L42)), so the bare-`data`-only shape consumes correctly without pretending to be a cursor endpoint. Cursor pagination on targets is genuinely out of scope (§3); shipping placeholder cursor fields would create a pseudo-contract that drifts from `api-conventions.md` §"Pagination" ("All list endpoints use cursor pagination") in spirit while not honoring it in form.

### 7.2 Contract rules

- Error body **MUST** include machine-readable `error_code`.
- Status codes **MUST** be deterministic per scenario: 404 for missing cluster, 403 for ACL-restricted, 503 for unreachable.
- The response shape **MUST** match `EntitySelectListPage<TargetInfo>` exactly so the frontend hook returns the raw response without translation.

### 7.3 Response examples

**Success (200 OK):**

```json
{
  "data": [
    { "name": "products", "doc_count": 47218 },
    { "name": "products_v2", "doc_count": 2 },
    { "name": "reviews", "doc_count": 1024 }
  ]
}
```

**Cluster not found (404):**

```json
{
  "detail": {
    "error_code": "CLUSTER_NOT_FOUND",
    "message": "cluster 0192f7d2-3a4b-7c8d-9e0f-112233445566 not found",
    "retryable": false
  }
}
```

**Cluster restricts listing — security plugin / ACL (403):**

```json
{
  "detail": {
    "error_code": "TARGETS_FORBIDDEN",
    "message": "cluster denied listing call (HTTP 403 from /_cat/indices)",
    "retryable": false
  }
}
```

**Cluster unreachable — network / 5xx (503):**

```json
{
  "detail": {
    "error_code": "CLUSTER_UNREACHABLE",
    "message": "HTTP 503 from /_cat/indices",
    "retryable": true
  }
}
```

Auth error shape: N/A — MVP1 no auth.

### 7.4 Enumerated value contracts

This feature does not introduce any new filters, status badges, sort keys, or dropdown values that go back to the backend. The target name itself is free-form string (no enum), and the wire/UI display name happens to match (`getId(t) = getLabel(t)`'s prefix). The new error codes are listed in §7.5 below — those are backend → frontend, not frontend → backend.

### 7.5 Error code catalog

| Code | HTTP Status | Meaning |
|---|---|---|
| `TARGETS_FORBIDDEN` | 403 | Engine refused the `_cat/indices` (or equivalent) listing call due to access control. `retryable: false` — the operator must enter the target manually. Frontend auto-engages manual mode on this code. |

Existing error codes reused by this endpoint (no spec change required):

| Code | HTTP Status | Source |
|---|---|---|
| `CLUSTER_NOT_FOUND` | 404 | `infra_adapter_elastic` |
| `CLUSTER_UNREACHABLE` | 503 | `infra_adapter_elastic`; `retryable: true` |

## 9) Data model and state transitions

### New/changed entities

**None.** This feature adds no tables, no columns, no migrations.

- `studies.target` is a VARCHAR column owned by `feat_study_lifecycle`; this feature does not change its type, constraints, or content.
- `TargetInfo` (Pydantic, in [`backend/app/adapters/protocol.py:67-71`](../../../../backend/app/adapters/protocol.py#L67-L71)) is reused unchanged. No `health` field is added (locked out of scope; see §4 Anti-patterns).
- A new Pydantic response wrapper `TargetListResponse` is added to `backend/app/api/v1/schemas.py` — pure response shape, no DB binding.

### Required invariants

- The new endpoint **MUST NOT** mutate any DB row. It's a pure read-path passthrough to the adapter.
- The endpoint **MUST NOT** instantiate `httpx.AsyncClient` or any engine SDK directly — adapter access is via the `acquire_adapter(cluster)` async context manager (CLAUDE.md Absolute Rule #4).

### State transitions

N/A — pure read endpoint.

### Idempotency/replay behavior

N/A — `GET` is idempotent by HTTP convention.

## 10) Security, privacy, and compliance

- **Threats:**
  1. *Cluster credential leak* — the new endpoint dispatches via `acquire_adapter` which resolves credentials from the mounted secrets file. No new code path exposes secrets. The endpoint does NOT echo any portion of the credential in the response or error message.
  2. *Information disclosure of internal index names* — `_cat/indices` returns all indices the configured credential can see. Operators registering a cluster with a high-privilege credential effectively expose every index in the dropdown. Mitigation: this matches the existing trust model of `/clusters/{id}/schema` (which already exposes mapping detail for any target the credential can read); no new threat surface.
  3. *Denial via repeated calls* — the endpoint is unauthenticated (MVP1). A misbehaving frontend (or operator hammering the modal) could spike `_cat/indices` traffic. Mitigation: bounded by TanStack `staleTime: 30_000` + `<EntitySelect>`'s "Retry" button is operator-initiated; no programmatic retry loop. Rate-limit middleware activates at MVP4 per [`api-conventions.md`](../../../01_architecture/api-conventions.md).
- **Controls:**
  - Credential resolution via `acquire_adapter` (existing mounted-secrets pattern, CLAUDE.md Rule #2).
  - Error envelope never includes credential material; messages cite HTTP status codes only.
- **Secrets/key handling:** No new secrets. Existing per-cluster credentials are resolved by `acquire_adapter` from `./secrets/<credentials_ref>`.
- **Auditability:** N/A — MVP1 has no `audit_log`. Pure read endpoint; no state change to audit even at MVP2+.
- **Data retention/deletion/export:** No data created. Target names are not persisted by this feature.

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement:** Unchanged. Create-study modal is reached via "New study" button on `/studies`. The target field stays at Step 1 of the wizard (positions: Cluster → Target → Step 2 Query set + Judgment list → Step 3 Template → Step 4 Search space → Step 5 Objective + plan).
- **Labeling taxonomy:** User-visible label stays `"Target index / collection"` ([create-study-modal.tsx:454](../../../../ui/src/components/studies/create-study-modal.tsx#L454)). Tooltip glossary key `study.target` is unchanged. New strings: `"Enter manually"` (toggle), `"Cluster restricts index listing — enter the target name manually."` (auto-engage hint), `"Choose a target"` (EntitySelect placeholder).
- **Content hierarchy:** Within Step 1: Cluster picker (primary, top) → Target picker (primary, below) → "{N} fields discovered" hint (secondary, below target). The "Enter manually" toggle is tertiary (subordinate text-button-style below the target picker, visible only when dropdown-mode is engaged).
- **Progressive disclosure:** Default view = dropdown mode. Operator clicks "Enter manually" → reveals the original `<Input>`. Operator clicks "Use dropdown" (toggle inverse label when in manual mode) → reverts. No animated transition required.
- **Relationship to existing pages:** This feature replaces the target widget inside the existing Step 1; nothing else moves.

### Tooltips and contextual help

| Element | Tooltip / help text | Trigger | Placement |
|---|---|---|---|
| "Target index / collection" label | Existing glossary entry `study.target` — `"The Elasticsearch index or OpenSearch collection name the study will tune against (e.g., 'products')."` Unchanged. | `hover` on adjacent `<InfoTooltip>` info icon | `top` |
| "Enter manually" toggle | `"Type the target name instead of picking from the cluster's index list."` | `hover` on the toggle button | `top` |
| EntitySelect error state | Built into the primitive — the disabled trigger shows `"Failed to load — click retry"` and the adjacent button is `"Retry"`. No spec change. | Default render on error | inline |
| EntitySelect empty state | Built into the primitive — disabled trigger shows the empty-state message. Spec sets `emptyState.message` = `"No targets found on this cluster."` and `emptyState.cta` = `{ label: "Enter manually", onClick: <flip toggle> }` (via the CTA prop). | Default render when `data.length === 0` | inline |
| Auto-engage hint (manual mode after TARGETS_FORBIDDEN) | `"Cluster restricts index listing — enter the target name manually."` | Inline amber text below the `<Input>` | `inline` |

Note on the empty-state CTA: `EntitySelectEmptyState.cta` is currently typed as `{ label, href }` (Next.js `<Link>`-based, see [`entity-select.tsx:33-36`](../../../../ui/src/components/common/entity-select.tsx#L33-L36)). Spec FR-5 requires an `onClick` variant for the toggle-flip case. **Implementation choice:** the page wraps the EntitySelect and renders its own empty-state message + button below the dropdown when `data.length === 0`, rather than extending the primitive's CTA type. Avoids primitive surface-area changes for a one-off use case.

### Target-change cascade (intentionally narrow)

Changing `target` (within the same cluster) does NOT cascade to other Step-1/2/3/4 fields. Rationale, captured to prevent a future "should this reset?" question:

| Field | Why no cascade |
|---|---|
| `query_set_id` (Step 2) | Query sets are filtered by `cluster_id`, not by `target`. A single query set's queries are typically reused across multiple targets on the same cluster. |
| `judgment_list_id` (Step 2) | Judgment lists are scoped to a `query_set_id`, transitively to a cluster — not to a target. |
| `template_id` (Step 3) | Templates are filtered by `engine_type`, not by target. The template's `declared_params` reference parameter names (e.g., `title_boost`), not target field names. |
| Step 4 `search_space_text` | The Step-4 auto-fill effect at [`create-study-modal.tsx:208-262`](../../../../ui/src/components/studies/create-study-modal.tsx#L208-L262) is keyed on `templateBody.declared_params` (the picked template), NOT on the discovered schema fields. A target switch within the same cluster never invalidates Step 4 state. |
| `useClusterSchema` "{N} fields discovered" hint | DOES re-fetch on target change (the hook's queryKey is `['clusters', id, 'schema', target]`) — this is the correct behavior (informational hint stays accurate without causing cascade resets). |

Cluster change still triggers the full cascade per FR-4.

### Primary flows

1. **Happy path — dropdown pick:** Operator opens "New study" → picks a cluster from the cluster dropdown → the target dropdown loads and shows `[products (47,218 docs), products_v2 (2 docs), reviews (1,024 docs)]` sorted alphabetically → operator picks "products" → schema query fires → "4 fields discovered" hint renders → operator clicks Next.
2. **Cluster swap mid-flow:** Operator picks cluster A, picks target "products", advances to Step 2, comes back to Step 1, swaps to cluster B → target field clears, query set / judgment list / template all clear (existing cascade), target dropdown reloads with cluster B's targets → operator picks fresh target.
3. **Manual mode (operator preference):** Operator opens modal → picks cluster → clicks "Enter manually" → typing `<Input>` appears with placeholder `"products"` → operator types `products` → schema query fires → "4 fields discovered" → Next.

### Edge/error flows

- **Cluster restricts listing (ACL-restricted cluster):** Operator picks cluster → `useClusterTargets` returns `ApiError(errorCode='TARGETS_FORBIDDEN')` → manual mode auto-engages → inline amber hint `"Cluster restricts index listing — enter the target name manually."` renders below the input → operator types target manually.
- **Cluster unreachable mid-flow:** Operator picks cluster → `useClusterTargets` returns `ApiError(errorCode='CLUSTER_UNREACHABLE', retryable=true)` → `<EntitySelect>`'s built-in error state renders disabled trigger + "Retry" button → operator clicks Retry → re-fetch.
- **No targets exist on cluster:** `useClusterTargets` returns `{ data: [] }` → EntitySelect renders empty-state per spec FR-4/§11 Tooltips (page-level wrapper shows `"No targets found on this cluster."` + "Enter manually" button).
- **Operator types nonexistent target in manual mode:** Schema query 404s; no toast (FR-6); "{N} fields discovered" hint silently doesn't render → operator notices and corrects.
- **Backend network drops between dropdown load and selection:** TanStack cache holds the prior result for `staleTime: 30s`; selection still succeeds. If the schema query fires next and the backend is still down, the schema query toasts `CLUSTER_UNREACHABLE` (preserved global toast — not in FR-6's suppress list).
- **Cluster soft-deleted between cluster picker render and target picker dispatch:** `useClusterTargets` returns `404 CLUSTER_NOT_FOUND` → EntitySelect renders disabled trigger + Retry; on retry, persists → operator picks a different cluster from the picker above (which has also revalidated and now omits the deleted cluster).

## 12) Given/When/Then acceptance criteria

### AC-1: Endpoint exposes the adapter listing (happy path)

- **Given** a cluster registered with engine `elasticsearch` and 3 user-facing indices (`products`, `reviews`, `orders`) + 1 system index (`.kibana_1`)
- **When** the client issues `GET /api/v1/clusters/{cluster_id}/targets`
- **Then** the response is `200 OK` with body shape `{ data: [TargetInfo×3] }` containing only `products`, `reviews`, `orders` (no `.kibana_1`).
- **Example values:**
  - Input: `GET /api/v1/clusters/0192f7d2-3a4b-7c8d-9e0f-112233445566/targets`
  - Expected response body:
    ```json
    {
      "data": [
        { "name": "orders", "doc_count": 152 },
        { "name": "products", "doc_count": 47218 },
        { "name": "reviews", "doc_count": 1024 }
      ]
    }
    ```
  - Sort order at the API layer is engine-defined (`_cat/indices` order); the frontend sorts alphabetically (FR-7). Backend integration tests assert membership, not order.

### AC-2: Endpoint returns 404 for unknown cluster

- **Given** no cluster with id `00000000-0000-0000-0000-000000000000` exists (or it is soft-deleted)
- **When** the client issues `GET /api/v1/clusters/00000000-0000-0000-0000-000000000000/targets`
- **Then** the response is `404` with body `{ "detail": { "error_code": "CLUSTER_NOT_FOUND", "message": "cluster 00000000-0000-0000-0000-000000000000 not found", "retryable": false } }`.

### AC-3: Endpoint returns 403 TARGETS_FORBIDDEN when ACL denies listing

- **Given** a cluster registered with credentials that return `403 Forbidden` on `GET /_cat/indices`
- **When** the client issues `GET /api/v1/clusters/{cluster_id}/targets`
- **Then** the response is `403` with body `{ "detail": { "error_code": "TARGETS_FORBIDDEN", "message": "...", "retryable": false } }`.

### AC-4: Endpoint returns 503 CLUSTER_UNREACHABLE when engine is down

- **Given** a cluster whose `base_url` points to an unreachable host (connection refused or 5xx)
- **When** the client issues `GET /api/v1/clusters/{cluster_id}/targets`
- **Then** the response is `503` with body `{ "detail": { "error_code": "CLUSTER_UNREACHABLE", "message": "...", "retryable": true } }`.

### AC-5: Adapter raises TargetsForbiddenError on 401/403

- **Given** an `ElasticAdapter` instance whose configured `_cat/indices` call returns HTTP `403`
- **When** test code calls `await adapter.list_targets()`
- **Then** `TargetsForbiddenError` is raised.
- **And given** the same call returns HTTP `401`
- **Then** `TargetsForbiddenError` is also raised.
- **And given** the same call returns HTTP `503`
- **Then** `ClusterUnreachableError` is raised (existing behavior preserved).

### AC-6: Frontend hook returns EntitySelectListPage-compatible shape directly

- **Given** the backend returns `{ data: [{name:"products", doc_count:42}] }`
- **When** a component calls `const q = useClusterTargets("c-123")` and reads `q.data`
- **Then** `q.data` equals `{ data: [{name:"products", doc_count:42}] }` (passes directly to `<EntitySelect query={q} />` without translation — `EntitySelectListPage<T>`'s `next_cursor` and `has_more` fields are optional so the bare-`data` shape consumes correctly).

### AC-7: EntitySelect renders target options sorted alphabetically

- **Given** the hook returns `data: [{name: "reviews"}, {name: "orders"}, {name: "products"}]`
- **When** the EntitySelect renders
- **Then** the rendered option order is `["orders", "products", "reviews"]` (case-insensitive alphabetical).

### AC-8: Changing cluster resets target field AND manual-mode toggle

- **Given** the operator has picked cluster A and target `products`
- **When** the operator changes the cluster to cluster B
- **Then** the form's `target` value resets to `""`, AND the dropdown re-fetches against cluster B, AND `query_set_id` / `judgment_list_id` / `template_id` also reset (existing cascade preserved).
- **And given** the operator was in manual mode on cluster A (either toggled manually OR auto-engaged via TARGETS_FORBIDDEN)
- **When** the operator changes the cluster to cluster B (which permits listing)
- **Then** the manual-mode toggle resets to off (dropdown mode), the `<EntitySelect>` is rendered, AND any prior `TARGETS_FORBIDDEN` inline hint is unmounted.

### AC-9: Manual mode toggle reveals the original input

- **Given** the operator is on Step 1 with dropdown mode (default)
- **When** the operator clicks "Enter manually"
- **Then** the `<EntitySelect>` is unmounted, the original `<Input id="cs-target">` is rendered with placeholder `"products"`, and the toggle label flips to "Use dropdown".
- **When** the operator clicks "Use dropdown"
- **Then** the `<Input>` is unmounted and the dropdown returns (with cached data, no re-fetch).

### AC-10: Manual mode auto-engages on TARGETS_FORBIDDEN

- **Given** the backend returns `403 TARGETS_FORBIDDEN` for `GET /clusters/{id}/targets`
- **When** the EntitySelect would normally render its error state
- **Then** manual mode is engaged instead (Input rendered), AND an inline amber text `"Cluster restricts index listing — enter the target name manually."` is shown below the input.

### AC-11: TARGET_NOT_FOUND no longer toasts globally, and fires exactly one request

- **Given** the operator is in manual mode and types `prodd` into the target input
- **When** the schema query fires
- **Then** the schema GET fires exactly once (FR-6: `retry` predicate short-circuits on `retryable: false`).
- **And** no toast is shown (FR-6: `meta.suppressErrorCodes: ['TARGET_NOT_FOUND']`).
- **And** the "{N} fields discovered" hint does NOT render (consistent with current schema-404 behavior).

### AC-13: TARGETS_FORBIDDEN fires exactly one request and does not toast

- **Given** the backend will return `403 TARGETS_FORBIDDEN` for the targets endpoint on cluster X
- **When** the operator picks cluster X and the targets query fires
- **Then** the targets GET fires exactly once (FR-3: `retry` predicate short-circuits on `retryable: false`).
- **And** no global toast is shown (FR-3: `meta.suppressErrorCodes: ['TARGETS_FORBIDDEN']`).
- **And** manual mode auto-engages with the inline amber hint per AC-10.

### AC-12: Modal open resets toggle to dropdown mode

- **Given** the operator opened the modal previously, flipped to manual mode, closed the modal
- **When** the operator re-opens the modal
- **Then** Step 1 renders in dropdown mode (toggle state not persisted across opens).

## 13) Non-functional requirements

- **Performance:** `GET /api/v1/clusters/{cluster_id}/targets` p95 latency ≤ engine round-trip + 50 ms overhead (matches existing `/schema` endpoint expectations). TanStack `staleTime: 30_000` (inherited default) keeps repeat opens cache-hit.
- **Reliability:** No new SLO. Endpoint inherits the cluster's connection reliability; `CLUSTER_UNREACHABLE` is the contract for transient failures.
- **Operability:** Standard structlog request envelope (`request_id`, `endpoint`, `status_code`) — inherited from FastAPI middleware. No new metrics or alerts.
- **Accessibility/usability:**
  - `<EntitySelect>` already supports keyboard navigation + screen-reader semantics (Radix Select).
  - "Enter manually" toggle is a `<button type="button">` with visible focus ring; `aria-pressed` reflects toggle state.
  - Inline amber hint on TARGETS_FORBIDDEN is announced by screen readers (rendered inline below the input; no `aria-live` needed because it appears synchronously with the mode switch).

## 14) Test strategy requirements (spec-level)

**Layered coverage required (CLAUDE.md "Testing Conventions"):**

- **Unit (`backend/tests/unit/adapters/`):**
  - `test_elastic.py` (new test module section) — assert `ElasticAdapter.list_targets()` raises `TargetsForbiddenError` on 401 + on 403; raises `ClusterUnreachableError` on connection failure + on 5xx; returns the existing happy-path shape on 200 (already covered, no regression).
  - `test_protocol.py` — extend Protocol shape test to assert `TargetsForbiddenError` is importable from `adapters.errors` and is a distinct subclass.
- **Integration (`backend/tests/integration/`):**
  - `test_clusters_api.py` — new `TestTargetsEndpoint` class with 2 cases against real ES + OpenSearch (already-seeded indices): (a) happy path returns ≥1 user-facing index + filters system indices; (b) asserts the response body shape is exactly `{"data": [{"name": str, "doc_count": int | None}, ...]}` with no extra keys.
  - `test_clusters_api_targets_errors.py` (or new section in existing file) — using the test database + a mocked adapter (`monkeypatch` on `acquire_adapter`): (a) 404 for missing cluster; (b) 403 from adapter → `TARGETS_FORBIDDEN`; (c) `ClusterUnreachableError` from adapter → `CLUSTER_UNREACHABLE`.
- **Contract (`backend/tests/contract/`):**
  - `test_openapi_surface.py` — `EXPECTED_ENDPOINTS` list gains `("get", "/api/v1/clusters/{cluster_id}/targets", "200")`.
  - `test_error_codes.py` — add `TARGETS_FORBIDDEN` envelope assertion.
  - `test_clusters_api_contract.py` — add `TargetListResponse` shape assertion against the OpenAPI schema.
- **Frontend unit (`ui/src/__tests__/`):**
  - `lib/api/clusters.test.ts` (or new) — `useClusterTargets` hook returns `{ data: TargetInfo[] }` shape directly; sets `enabled: false` when `clusterId` is empty; **retry predicate fires exactly one request on `TARGETS_FORBIDDEN` and `CLUSTER_NOT_FOUND`** (mock the api-client to assert call count); retries on `CLUSTER_UNREACHABLE` per default. Similar assertion for `useClusterSchema` on `TARGET_NOT_FOUND`.
  - `components/studies/create-study-modal.test.tsx` (existing file, extended) — dropdown mode renders EntitySelect; manual mode renders Input; toggle flips between them; cluster change resets `target`; TARGETS_FORBIDDEN auto-engages manual mode with inline hint; **no global toast fires on TARGET_NOT_FOUND or TARGETS_FORBIDDEN** (mock `toast.error`, assert never called); FR-7 alphabetical sort assertion on rendered options.
  - **Mock discipline (mandatory):** every new modal test that exercises an `<EntitySelect>` inside the create-study `<Dialog>` MUST use the canonical shadcn-select mock helper at [`ui/src/__tests__/helpers/shadcn-select-mock.tsx`](../../../../ui/src/__tests__/helpers/shadcn-select-mock.tsx) via the 3-line dynamic-`import()` inside `vi.mock` pattern documented at [`ui-architecture.md` §"Modal-level testing"](../../../01_architecture/ui-architecture.md). Without the mock, jsdom + Radix focus-trap recursion crashes the test before assertions run.
- **E2E (`ui/tests/e2e/`):**
  - `studies-create.spec.ts` (existing real-backend spec) — add 1 case: seed cluster + 2 targets → open modal → pick cluster → assert dropdown options visible → pick `products` → advance through Steps 2–5 → submit → assert created study's `target` field equals `products` in the API response.
  - **No `page.route()` mocking of `/api/v1/clusters/{id}/targets`** — must use the real backend per [CLAUDE.md "E2E Testing Rules"](../../../../CLAUDE.md).

**Coverage gate:** project-wide 80% backend Python (pyproject `[tool.coverage.report].fail_under = 80`). New endpoint, hook, and adapter branches must be covered by the tests above.

## 15) Documentation update requirements

- `docs/01_architecture/api-conventions.md` — § "Standard error codes" gains a row for `TARGETS_FORBIDDEN` (403, `retryable: false`).
- `docs/01_architecture/adapters.md` — § "The Protocol" `list_targets()` line updated to mention that ACL/auth failures raise `TargetsForbiddenError` (sibling to `get_schema`'s `TargetNotFoundError` mention).
- `docs/01_architecture/ui-architecture.md` — § "Form dropdown primitive" gets a one-line note that the target picker in the create-study modal uses `<EntitySelect>` with a manual-mode fallback (new pattern; no other surface uses this combo today).
- `docs/00_overview/planned_features/` → move to `implemented_features/<YYYY_MM_DD>_feat_create_study_target_autocomplete/` after merge (per `/impl-execute` finalization).
- `docs/03_runbooks/` — N/A (no new operational procedure).
- `docs/04_security/` — N/A (no new threat surface; existing trust model preserved).
- `docs/05_quality/testing.md` — N/A (test layers and ratios unchanged).
- `architecture.md` — N/A (no new top-level layer or critical flow).
- `state.md` — append to recent changes; update Alembic head only if new migrations land (none here).
- `CLAUDE.md` — N/A (no new convention, env var, or rule).

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** None. Single-tenant MVP1 deploys ship the feature on merge; no per-customer rollout surface exists.
- **Migration/backfill expectations:** None. No schema changes.
- **Operational readiness gates:**
  - `make lint`, `make typecheck`, `make test` all green.
  - Pre-push gate per [CLAUDE.md "Build, Test, and Lint Commands"](../../../../CLAUDE.md): `make fmt && make lint && make typecheck && make test`.
  - UI gates: `cd ui && pnpm lint && pnpm typecheck && pnpm test && pnpm build`.
  - E2E green against the real local stack.
- **Release gate:** PR CI green + Gemini Code Assist findings adjudicated per CLAUDE.md "Before considering a PR ready to merge" + final GPT-5.5 review pass clean.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 (REST endpoint) | AC-1, AC-2, AC-3, AC-4 | Backend story B1 (router + Pydantic response model) | `test_openapi_surface.py`, `test_error_codes.py`, `test_clusters_api.py::TestTargetsEndpoint`, `test_clusters_api_targets_errors.py`, `test_clusters_api_contract.py` | `api-conventions.md` |
| FR-2 (adapter distinguishes 401/403) | AC-3, AC-5 | Backend story B2 (adapter error class + status mapping) | `test_elastic.py` (adapter unit), `test_protocol.py` (import + isinstance) | `adapters.md` |
| FR-3 (TanStack hook) | AC-6 | Frontend story F1 (hook) | `lib/api/clusters.test.ts` | — |
| FR-4 (replace Input + cascade reset) | AC-1 (smoke), AC-6, AC-8 | Frontend story F2 (modal swap + cascade) | `components/studies/create-study-modal.test.tsx`, `studies-create.spec.ts` (E2E happy path) | `ui-architecture.md` |
| FR-5 (manual-mode toggle + auto-engage) | AC-9, AC-10, AC-12 | Frontend story F3 (toggle + auto-engage) | `components/studies/create-study-modal.test.tsx` (toggle cases) | `ui-architecture.md` |
| FR-6 (silence TARGET_NOT_FOUND noise — toast + retry storm) | AC-11 | Frontend story F4 (meta + retry predicate) | `components/studies/create-study-modal.test.tsx` (toast assertion + GET-count assertion), `lib/api/clusters.test.ts` (retry predicate) | — |
| FR-7 (alphabetical sort) | AC-7 | Frontend story F2 (sort inside hook OR EntitySelect consumer) | `components/studies/create-study-modal.test.tsx` (sort assertion) | — |
| FR-3 (retry predicate + suppress TARGETS_FORBIDDEN toast) | AC-13 | Frontend story F1 (hook) | `lib/api/clusters.test.ts` (retry + meta), `components/studies/create-study-modal.test.tsx` (toast assertion) | — |

## 18) Definition of feature done

This feature is complete when:

- [ ] All AC-1 through AC-13 pass in CI.
- [ ] Unit + integration + contract + E2E layers green.
- [ ] Backend coverage gate (80%) satisfied.
- [ ] `api-conventions.md`, `adapters.md`, `ui-architecture.md` updates merged.
- [ ] PR Gemini Code Assist findings adjudicated per CLAUDE.md.
- [ ] Final GPT-5.5 review clean.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

(All `/idea-preflight` open questions resolved during spec generation — defaults applied. None remaining at plan-creation time.)

### Decision log

- **2026-05-20** — Vocabulary uses "targets" not "indexes" on every wire surface (method name, endpoint, hook name, error code, response field, test names). User-visible label stays "Target index / collection". Rationale: matches the adapter Protocol (`SearchAdapter.list_targets`, `TargetInfo`), the `?target=...` query param on `/schema`, the `studies.target` column, the umbrella spec's cross-engine vocab (Fusion = collection, Solr = core). Vocab drift across the wire is a long-tail maintenance burden.
- **2026-05-20** — No Protocol change. The Pydantic `TargetInfo` model and `SearchAdapter.list_targets()` Protocol method are reused as-is. Only the `ElasticAdapter` implementation gains a 401/403 → `TargetsForbiddenError` mapping (mirroring the existing 404 → `TargetNotFoundError` pattern in `get_schema`).
- **2026-05-20** — Added `TargetsForbiddenError` as a new exception class (NOT planned in the original idea, which assumed zero adapter changes). Rationale: without distinguishing 401/403 from 5xx at the adapter, the frontend cannot route ACL-restricted clusters to manual mode (the only sane UX). The change is ~10 LOC + matches an established pattern; cost is well below the operator-confusion cost of conflating the two failure modes.
- **2026-05-20** — Per-target health visualization dropped (locked out of scope §3). Rationale: requires extending `TargetInfo` (Protocol-level change) + adapter `_cat/indices` `h=` query param + 3 test files + frontend rendering — all for a noisy single-node-dev signal. Defer if real users ask.
- **2026-05-20** — Response shape is unpaginated `{ data: list[TargetInfo] }` (no `next_cursor` or `has_more` fields — superseded by the cycle-1 GPT-5.5 review fix below). Rationale: matches `/clusters/{id}/schema` precedent (sub-resource lookup, not queryable list); bounded target counts (<200) make cursor pagination ceremonial; placeholder cursor fields would create a pseudo-contract that drifts from `api-conventions.md` discipline.
- **2026-05-20** — Sort frontend-side alphabetical by `name`. Rationale: `_cat/indices` returns indices in engine-defined order (typically creation order); alphabetical is the canonical "find what I'm looking for" sort. Doc count is shown in the label but doesn't drive order.
- **2026-05-20** — Manual-mode toggle resets to dropdown mode on every modal open. Rationale: modal is short-lived; ACL-restricted clusters are the exception; carrying toggle state across opens confuses operators who switched clusters since the last session.
- **2026-05-20** — `<EntitySelect>`'s built-in empty-state CTA prop is `{label, href}` (Next.js `<Link>`). Spec requires a button-onClick variant for the toggle-flip case (FR-5). Decision: don't extend the primitive's CTA type — the create-study modal page renders its own empty-state message + toggle-flip button below the `<EntitySelect>` when `data.length === 0`. Keeps the primitive's surface area minimal; the empty-state path is the only place we'd diverge from the existing CTA shape.
- **2026-05-20** — FR-6 (suppress TARGET_NOT_FOUND toast) bundled into Phase 1 even though the dropdown path doesn't trigger schema 404s. Rationale: the manual-mode `<Input>` still fires `useClusterSchema` on every keystroke; without the suppression, every typo toasts. Cost: 3 LOC; payoff: silence the toast across both the dropdown empty-state retype path and the auto-engaged TARGETS_FORBIDDEN path.
- **2026-05-20** — Cycle-1 GPT-5.5 review accepted: dropped the placeholder `next_cursor: null, has_more: false` fields from `TargetListResponse`. Pseudo-cursor-pagination drifts from `api-conventions.md` discipline; `EntitySelectListPage<T>`'s optional fields make the bare `{ data: TargetInfo[] }` shape consumable as-is. See §7.1 pagination shape rationale.
- **2026-05-20** — Cycle-1 GPT-5.5 review accepted: FR-3 + FR-6 both gain a `retry` predicate that short-circuits on `error.retryable === false`. Without it, ACL-restricted clusters fire 4× and global toasts fire on both TARGETS_FORBIDDEN and TARGET_NOT_FOUND despite `meta.suppressErrorCodes` (the toast logic and the retry logic are independent — `meta.suppressErrorCodes` silences the toast but TanStack still retries). Also added `meta.suppressErrorCodes: ['TARGETS_FORBIDDEN']` to `useClusterTargets` so the auto-engage hint is the only signal the operator sees. AC-13 added.
- **2026-05-20** — Cycle-1 GPT-5.5 review accepted: §14 test strategy now requires the canonical `shadcn-select-mock.tsx` helper for every new modal test that exercises `<EntitySelect>` inside a `<Dialog>`. Without it, Radix focus-trap recursion under jsdom crashes the test before assertions run.
- **2026-05-20** — Cycle-1 GPT-5.5 review rejected with counter-evidence: claim that "target change should cascade to Step 4 schema-derived state." Counter-evidence: Step 4's auto-fill effect at [`create-study-modal.tsx:208-262`](../../../../ui/src/components/studies/create-study-modal.tsx#L208-L262) is keyed on `templateBody.declared_params`, not on `useClusterSchema`'s discovered fields. Target change correctly re-fetches the informational schema hint without staling Step 4. Added §11 "Target-change cascade (intentionally narrow)" table documenting this.
- **2026-05-20** — Cycle-1 GPT-5.5 review rejected with counter-evidence: claim that the new `TargetsForbiddenError` is "scope drift from the idea's locked decision #2 (no Protocol or adapter changes)." Counter-evidence: (a) the locked decision text says "No new Protocol method or adapter implementation" — the spec adds neither (the Protocol method exists; the adapter implementation method exists; what changes is the existing method's error-mapping, which is an internal refinement matching the established `get_schema` 404→`TargetNotFoundError` pattern); (b) deferring would leave ACL-restricted clusters returning `CLUSTER_UNREACHABLE` with `retryable: true`, triggering 3× api-client retries on what is a permanent permission failure AND blocking the auto-engage UX nicety from FR-5; (c) the change is ~10 LOC. Spec keeps the scope expansion explicit in this decision log.
- **2026-05-20** — Cycle-2 GPT-5.5 review accepted: dropped `next_cursor` and `has_more` from every remaining mention in FR-1, AC-1, AC-6, §14 integration test description, and the earlier §19 decision-log entry. The cycle-1 patch left those references stale, contradicting §7.1's bare-`data`-only contract. Now consistent end-to-end.
- **2026-05-20** — Cycle-2 GPT-5.5 review accepted: FR-5 now requires resetting the manual-mode toggle (and clearing any inline TARGETS_FORBIDDEN hint) on cluster change, in parallel with the FR-4 `target` reset. AC-8 extended with the manual-mode reset assertion. Without this, an operator who auto-engaged manual mode on cluster A would stay in manual mode on cluster B even when B permits target listing — losing the discovery UX that motivates the whole feature.
- **2026-05-20** — Cycle-2 GPT-5.5 review accepted: §18 Definition of Done updated from "AC-1 through AC-12" to "AC-1 through AC-13" — the cycle-1 patch added AC-13 (TARGETS_FORBIDDEN no-retry/no-toast) but forgot to bump the §18 counter.
