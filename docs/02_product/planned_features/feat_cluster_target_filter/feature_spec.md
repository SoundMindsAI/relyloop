# Feature Specification — Per-cluster target filter

**Date:** 2026-05-20
**Status:** Draft
**Owners:** soundminds.ai (product + engineering)
**Related docs:**
- [`idea.md`](idea.md) — input brief (preflighted, 4 locked decisions, 0 open questions)
- [`docs/01_architecture/adapters.md`](../../../01_architecture/adapters.md) — SearchAdapter Protocol
- [`docs/01_architecture/data-model.md`](../../../01_architecture/data-model.md) — `clusters` table
- [`docs/00_overview/implemented_features/2026_05_20_feat_create_study_target_autocomplete/feature_spec.md`](../../../00_overview/implemented_features/2026_05_20_feat_create_study_target_autocomplete/feature_spec.md) — parent feature

---

## 1) Purpose

- **Problem:** `ElasticAdapter.list_targets()` at [`elastic.py:358-411`](../../../../backend/app/adapters/elastic.py#L358-L411) returns every user-facing index the engine credential can see. When multiple logical RelyLoop "clusters" point at one physical engine (multi-team shared ES; the demo's 1-engine-3-clusters state surfaced 2026-05-20 during demo re-seeding), the create-study Step-1 target dropdown cross-pollinates — every cluster shows every cluster's indices.
- **Outcome:** Each registered cluster can optionally carry a glob pattern (`products*`, `team-a-*`, `docs-{en,fr}-*`) that scopes `list_targets()` to the matching subset. Default `null` = today's behavior (every user-facing index). Real-world payoff: enterprise ops register one cluster registration per team's index family without spinning up separate physical engines.
- **Non-goal:** Per-credential ACL filtering (that's an ES security plugin concern). Edit-after-registration (`PATCH /clusters/{id}` for `target_filter`) — deferred to a follow-up `chore_cluster_update_target_filter` per idea Locked Decision #3.

## 2) Current state audit

### Existing implementations

| Surface | Location | Behavior today |
|---|---|---|
| `clusters` ORM model | [`backend/app/db/models/cluster.py:24-86`](../../../../backend/app/db/models/cluster.py#L24-L86) | 13 columns: `id, name, engine_type, environment, base_url, auth_kind, credentials_ref, config_repo_id, config_path, engine_config, notes, created_at, deleted_at`. No filter-like column. |
| `CreateClusterRequest` Pydantic | [`backend/app/api/v1/schemas.py:50-67`](../../../../backend/app/api/v1/schemas.py#L50-L67) | Mirrors the model — 8 settable fields. Validates `base_url` scheme + private-IP. |
| `register_cluster` service | [`backend/app/services/cluster.py:83`](../../../../backend/app/services/cluster.py#L83) | Builds an adapter, probes via `health_check`, inserts the row via `repo.create_cluster(**fields)`. |
| `create_cluster` repo | [`backend/app/db/repo/cluster.py:39-41`](../../../../backend/app/db/repo/cluster.py#L39-L41) | One-line `Cluster(**fields)` + `db.add` — any field the model accepts is fine. |
| `ElasticAdapter.list_targets()` | [`elastic.py:358-411`](../../../../backend/app/adapters/elastic.py#L358-L411) | Calls `_cat/indices?format=json&h=index,docs.count`; filters `name.startswith('.')` system indices; returns `TargetInfo[]`. Post-`feat_create_study_target_autocomplete` (PR #165) — has the 401/403 → `TargetsForbiddenError` + `httpx.HTTPError` defensive catches. |
| `GET /api/v1/clusters/{cluster_id}/targets` router | [`backend/app/api/v1/clusters.py:326-358`](../../../../backend/app/api/v1/clusters.py#L326-L358) | Thin passthrough: fetches the cluster, calls `acquire_adapter(cluster).list_targets()`, returns `TargetListResponse{data: TargetInfo[]}`. |
| `useClusterTargets(clusterId)` hook | [`ui/src/lib/api/clusters.ts:120-140`](../../../../ui/src/lib/api/clusters.ts#L120-L140) (post-PR #165) | TanStack hook with retry predicate + `meta.suppressErrorCodes`. Consumed by Step 1 of the create-study modal. |
| `register-cluster-modal.tsx` | [`ui/src/components/clusters/register-cluster-modal.tsx`](../../../../ui/src/components/clusters/register-cluster-modal.tsx) | Has a `Notes` Textarea pattern at line 230-231 — model for adding the new `target_filter` Input. |
| Endpoint surface | Verified — `/clusters/{id}` accepts GET + DELETE only. **No PATCH.** No `update_cluster` service helper. No `UpdateClusterRequest` Pydantic. | Locked Decision #3 (idea): create-only filter; PATCH is a follow-up. |

### Navigation and link impact

None. No new pages, no URL changes. The new field surfaces inside the existing `/clusters` register modal + flows through the existing `/api/v1/clusters/{id}/targets` endpoint with no API path change.

### Existing test impact

| Test file | Pattern | Required action |
|---|---|---|
| `backend/tests/unit/adapters/test_elastic_schema.py` (the `TestListTargets` class) | 5 existing cases for `list_targets()` (filter system indices, 401/403, 5xx, connection-error) | Add 4 cases for `target_filter` behavior (null = pass-through; matches subset; matches none; literal vs glob). |
| `backend/tests/integration/test_clusters_api.py` (`TestTargetsEndpoint`) | Real ES + OpenSearch happy-path | Add 1 case: register a cluster with `target_filter="products*"`, assert only matching indices returned. |
| `backend/tests/contract/test_clusters_api_contract.py` | Pydantic schema importability + shape assertions | Add `target_filter` to `CreateClusterRequest` shape assertion. |
| `backend/tests/contract/test_openapi_surface.py` | `EXPECTED_ENDPOINTS` list | No change (no new endpoints). |
| `ui/src/__tests__/components/clusters/*.test.tsx` | Modal rendering + form submission | Extend `register-cluster-modal.test.tsx` with 1 case: filling `target_filter`, asserting it's passed in the request body. |

### Existing behaviors affected by scope change

| Behavior | Current | New | Decision needed |
|---|---|---|---|
| `GET /clusters/{id}/targets` for a cluster with no filter | Returns every user-facing index | Unchanged (filter is `null` → pass-through) | No (locked: backward-compatible) |
| `GET /clusters/{id}/targets` for a cluster WITH filter set | N/A (column doesn't exist yet) | Returns only `[t for t in user_facing_targets if fnmatch.fnmatch(t.name, target_filter)]` | No (FR-3) |
| Create-study Step-1 dropdown empty-state | Renders `"No targets found on this cluster."` from `<EntitySelect>`'s empty-state | When filter is set AND yields zero matches, the modal should differentiate: `"No targets match filter \"<filter>\" on this cluster. Update the cluster registration to relax it."` | No (FR-5) |
| Cluster registration form | 7 fields (name, engine_type, environment, base_url, auth_kind, credentials_ref, notes) | Adds an optional `target_filter` field between `Notes` and the submit row | No (FR-4) |

---

## 3) Scope

### In scope

- (FR-1) Add `target_filter: VARCHAR(256) NULL` column to `clusters` via Alembic migration `0014_clusters_target_filter`.
- (FR-2) Extend `CreateClusterRequest` Pydantic with optional `target_filter: str | None`, max_length=256, validated via `fnmatch.translate()`.
- (FR-3) `ElasticAdapter.list_targets()` accepts an optional `target_filter: str | None` parameter; when set, applies `fnmatch.fnmatch(name, target_filter)` AFTER the existing system-index filter. Router passes `cluster.target_filter` through.
- (FR-4) Frontend register-cluster modal adds an optional "Target filter (optional)" input between `Notes` and the submit row, with helper text + glob example.
- (FR-5) Create-study Step-1 modal's `<EntitySelect>` `emptyState.message` differentiates: cluster has zero targets vs filter excludes everything. Requires fetching `cluster.target_filter` from `/api/v1/clusters/{id}` detail (already returned by `ClusterDetail` if we add the field).
- (FR-6) The new column appears on `ClusterDetail` + `ClusterSummary` response models so the UI can read it.

### Out of scope

- **PATCH endpoint for `target_filter` editing** (Locked Decision #3 — operators DELETE + re-register; deferred to `chore_cluster_update_target_filter` follow-up).
- **Regex syntax** (Locked Decision #1 — glob only).
- **Server-side filtering at the engine level via `_cat/indices?index=<glob>`** (Locked Decision #2 — client-side in adapter; portable to OpenSearch + future engines).
- **Cascade validation** when filter excludes an existing study's `target` (Locked Decision #4 — existing studies keep working; the filter only constrains the picker for NEW studies).
- **Per-engine filter syntax differences** (Fusion/Solr support different glob semantics — we ship one syntax: Python `fnmatch`).
- **Inline editing of `target_filter` from the cluster-detail page** (PATCH scope; deferred).

### API convention check

- **Endpoint prefix:** No new endpoints. Existing `GET /api/v1/clusters/{cluster_id}/targets` is the only consumer.
- **Router file:** `backend/app/api/v1/clusters.py` (existing modifications).
- **Non-auth error envelope:** No new error codes. Existing `CLUSTER_NOT_FOUND` / `CLUSTER_UNREACHABLE` / `TARGETS_FORBIDDEN` cover the targets endpoint.
- **`target_filter` validation failure on POST /clusters:** Pydantic `VALIDATION_ERROR` (422) via `Field(max_length=256)` + a `@field_validator` calling `fnmatch.translate()`.
- **Pagination:** N/A (targets endpoint is unpaginated per `feat_create_study_target_autocomplete` spec §7.1).

### Phase boundaries

Single-phase feature. No deferred phases tracked. PATCH support (the one omitted capability) lives in a separate `chore_cluster_update_target_filter/idea.md` follow-up, NOT a deferred phase of this feature.

## 4) Product principles and constraints

- **Backward compatible:** `target_filter=null` (the default for existing rows in the migration) preserves today's behavior exactly. No existing study breaks. No existing cluster registration breaks. Migration up-and-downgrade round-trips without data loss.
- **Filter applies AFTER system-index exclusion.** Order: `(not name.startswith('.')) AND fnmatch(name, filter)`. Operators cannot accidentally re-expose `.kibana_1` via a `*` filter.
- **Single source of truth for filter semantics:** Python `fnmatch.fnmatch` (case-sensitive, supports `*`, `?`, `[seq]`, `[!seq]`). Documented in the new field's helper text + API field description.
- **CLAUDE.md Absolute Rule #4** (engine-specific code lives in adapter): the filter logic lives in `ElasticAdapter.list_targets()`. The router passes the filter string through without interpretation.
- **CLAUDE.md Absolute Rule #5** (migrations include `downgrade()` + round-trip cleanly): `0014` adds the column with default `NULL`; downgrade drops it.

### Anti-patterns

- **Do not** apply the filter in the router instead of the adapter. The adapter is where engine-specific name-handling lives (different engines may apply filters differently when we add Fusion/Solr); filtering in the router would split engine concerns across two layers.
- **Do not** validate at registration that the filter matches at least one current index. The cluster's index inventory changes over time; a filter that matches nothing today may match everything next week. Validate syntax only (`fnmatch.translate()`); leave content-emptiness to the empty-state UI message.
- **Do not** introduce a `cluster.PATCH` endpoint as part of this feature. Per Locked Decision #3, that's scope creep; defer to a sibling chore. Operators who need to change a filter today can DELETE + re-register.
- **Do not** add a `target_filter` field to existing studies. `studies.target` is a free-text column; if the filter later excludes that target, the study keeps working (Locked Decision #4 — no cascade). The filter is a picker-scoping concern, not a study-validity concern.
- **Do not** combine multiple filter patterns into one column (`products*,docs*`). Single glob only. If operators need OR-of-globs, they register two clusters.
- **Do not** treat empty-string `target_filter=""` as "match everything." That's confusing; empty string is rejected at validation, only `null` means "no filter."

## 5) Assumptions and dependencies

- **Dependency:** `feat_create_study_target_autocomplete` (shipped 2026-05-20 as PR #165 squash `bd4516a`) — provides the `list_targets()` adapter method + REST endpoint + `useClusterTargets` hook + Step-1 dropdown UI.
  - **Why required:** This feature ADDS a scoping field. Without the parent feature, there's no target-listing surface to scope.
  - **Status:** Implemented + merged to main.
  - **Risk if missing:** Zero — dependency satisfied.
- **Dependency:** Alembic head `0013_search_vector_conversations`. Next revision = `0014`.
- **No external dependencies.** No new services, no new env vars, no new secrets.

## 6) Actors and roles

- **Primary actor:** Relevance engineer registering a cluster (sets the filter at create time).
- **Secondary actor:** Relevance engineer creating a study (sees the filtered dropdown).
- **Role model:** N/A — RelyLoop MVP1 is single-tenant + no auth per [`tech-stack.md` §"Canonical release matrix"](../../../01_architecture/tech-stack.md).

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — MVP1 has no `audit_log`. When MVP2 lands, `cluster.target_filter` writes (both at registration and at the future PATCH) should emit `CLUSTER_TARGET_FILTER_CHANGED` events with metadata `{old: str|null, new: str|null}`. Documented here for the MVP2 backfill spec to pick up.

## 7) Functional requirements

### FR-1: New `clusters.target_filter` column

- Requirement:
  - The migration `migrations/versions/0014_clusters_target_filter.py` **MUST** add `target_filter VARCHAR(256) NULL` to the `clusters` table.
  - `downgrade()` **MUST** drop the column.
  - Round-trip (`alembic upgrade head && alembic downgrade -1 && alembic upgrade head`) **MUST** succeed on a populated DB without data loss on the other 11 columns.
- Notes: No index on the column — it's only read in single-row fetches inside `list_cluster_targets`, never in a `WHERE` clause across rows.

### FR-2: `CreateClusterRequest` accepts `target_filter`

- Requirement:
  - The Pydantic `CreateClusterRequest` at [`backend/app/api/v1/schemas.py:50`](../../../../backend/app/api/v1/schemas.py#L50) **MUST** declare `target_filter: str | None = Field(default=None, min_length=1, max_length=256)`.
  - A `@field_validator('target_filter')` **MUST** strip leading/trailing whitespace AND reject the post-strip empty string (returns the stripped value, or raises `ValueError` if stripped value is empty — surfaces as 422 `VALIDATION_ERROR`).
  - Empty-string `""` and whitespace-only strings **MUST** be rejected (422). Only `null` (omitted from the request body) means "no filter".
  - The `register_cluster` service **MUST** pass `target_filter` through to `repo.create_cluster(**fields)` unchanged.
- Notes: Glob syntax is NOT validated at registration. Python `fnmatch` is permissive — every non-empty string ≤256 chars is a valid pattern (unmatched `[`, lone `?`, etc. all match literally rather than raising). The user-meaningful validation here is length + non-empty; deeper syntax checks would just reject patterns that today match something operators might genuinely want.

### FR-3: `list_targets()` applies the filter

- Requirement:
  - The `SearchAdapter` Protocol at [`backend/app/adapters/protocol.py:131`](../../../../backend/app/adapters/protocol.py#L131) **MUST** be updated: `list_targets(self, *, request_id: str | None = None, target_filter: str | None = None) -> list[TargetInfo]`. Required so consumers typed against the Protocol can pass the kwarg.
  - `ElasticAdapter.list_targets()` concrete implementation **MUST** match the Protocol signature.
  - `StubAdapter.list_targets()` at [`backend/tests/integration/fixtures/stub_adapter.py:57`](../../../../backend/tests/integration/fixtures/stub_adapter.py#L57) **MUST** also accept the new kwarg (accept + ignore is fine — the stub's filtering isn't load-bearing for the tests that use it).
  - When `target_filter` is set, the existing row loop **MUST** apply `fnmatch.fnmatchcase(name, target_filter)` AFTER the existing `name.startswith('.')` system-index exclusion. Using `fnmatchcase` (NOT `fnmatch`) is mandatory: plain `fnmatch.fnmatch` calls `os.path.normcase`, which case-folds on macOS/Windows but not Linux — that would produce environment-dependent behavior. ES index names are case-sensitive; `fnmatchcase` matches that semantics on every platform.
  - When `target_filter` is `None`, the loop **MUST** behave identically to today (regression-tested by the existing 5 `TestListTargets` cases).
  - The router `list_cluster_targets` at [`clusters.py:326`](../../../../backend/app/api/v1/clusters.py#L326) **MUST** pass `cluster.target_filter` to the adapter.
- Notes: Order of operations matters. System-index filter first, glob filter second. Reverse order would allow a `.*` filter to surface system indices.

### FR-4: Register-cluster modal adds the field

- Requirement:
  - The register-cluster modal at [`register-cluster-modal.tsx`](../../../../ui/src/components/clusters/register-cluster-modal.tsx) **MUST** add a labeled `<Input id="cl-target-filter">` field between the existing `Notes` field (line 230-231) and the submit row.
  - Helper text **MUST** read: `"Glob pattern restricting which indices appear in the target picker for this cluster. Supports * (any chars), ? (single char), and [seq] / [!seq] character classes. Example: products* matches every index starting with 'products'. Brace expansion ({a,b}) is NOT supported — register two clusters if you need OR-of-globs. Leave blank to show every user-facing index."`
  - The form **MUST** submit `target_filter: values.target_filter.trim() || null` (whitespace-only OR empty string converts to null, matching the existing `notes` pattern at line 83). Trim BEFORE the empty check.
- Notes: Field placement intentionally below `Notes` because it's optional + advanced. Most operators leave it blank. The "no brace expansion" callout in the helper text exists because Python `fnmatch` (the validator we use) doesn't support `{a,b}` — operators familiar with bash globs would otherwise type `docs-{en,fr}-*` expecting OR-semantics and silently get zero matches.

### FR-5: Empty-state message differentiates filter vs no-targets

- Requirement:
  - The create-study modal Step 1 **MUST** read `selectedCluster.target_filter` via `selectedCluster` (already derived from `useClusters` at [`create-study-modal.tsx:144`](../../../../ui/src/components/studies/create-study-modal.tsx#L144)).
  - When `useClusterTargets` returns `{data: []}` AND `selectedCluster.target_filter` is non-null, the `<EntitySelect>`'s `emptyState.message` **MUST** be: `"No targets match filter \"<filter>\" on this cluster. To change the filter, delete and re-register the cluster — MVP1 has no in-place edit for cluster registrations."`
  - When `useClusterTargets` returns `{data: []}` AND `target_filter` is null, the existing message **MUST** be preserved: `"No targets found on this cluster."`
- Notes: The empty-state copy intentionally matches MVP1's actual recovery affordances (DELETE + re-register). Per Locked Decision #3 there's no PATCH endpoint and no edit modal; telling the operator to "update the cluster's target filter" would point at an unavailable action. The MVP4 follow-up `chore_cluster_update_target_filter` will replace this copy with an in-place edit CTA when the PATCH endpoint ships.

### FR-6: `ClusterDetail` + `ClusterSummary` expose `target_filter`

- Requirement:
  - Both response models **MUST** include `target_filter: str | None`.
  - The existing `_summary()` helper at [`clusters.py:116`](../../../../backend/app/api/v1/clusters.py#L116) and equivalent detail builder **MUST** populate the field from `cluster.target_filter`.
- Notes: Required so the frontend can read the filter value for FR-5's empty-state branch.

## 8) API and data contract baseline

### 7.1 Endpoint surface

No new endpoints. Two existing endpoints gain a new field/parameter:

| Method | Path | Change | Key error codes |
|---|---|---|---|
| `POST` | `/api/v1/clusters` | New optional body field `target_filter: str` | `VALIDATION_ERROR` (422) if pattern is invalid glob OR length > 256 OR empty string |
| `GET` | `/api/v1/clusters/{cluster_id}` | Response gains `target_filter` field | No change |
| `GET` | `/api/v1/clusters` | Each `ClusterSummary` gains `target_filter` field | No change |
| `GET` | `/api/v1/clusters/{cluster_id}/targets` | Server-side: filter applied when cluster has one set | No change (same `TargetListResponse` shape) |

### 7.2 Contract rules

- The `target_filter` field is **optional** on the request and **always present** on the response (as `null` when not set). Frontend code must handle both `null` and string values.
- Pattern validation is **syntactic only** (must be parseable by `fnmatch.translate()`). Content-matching is not validated at registration.
- When `target_filter` is set, the targets endpoint response shape is unchanged — same `{data: TargetInfo[]}`. Operators downstream can't distinguish a filter-zero-match from a no-indices result via the response shape; only via the field on `ClusterDetail`.

### 7.3 Response examples

**Cluster registration with filter (201 Created):**

```json
{
  "id": "019e470c-96aa-7412-9e68-2d1101f80cb0",
  "name": "acme-products-prod",
  "engine_type": "elasticsearch",
  "environment": "prod",
  "base_url": "http://elasticsearch:9200",
  "auth_kind": "es_basic",
  "engine_config": null,
  "notes": null,
  "target_filter": "products*",
  "created_at": "2026-05-20T20:30:00Z",
  "health_check": {
    "status": "green",
    "version": "9.4.0",
    "checked_at": "2026-05-20T20:30:00Z",
    "error": null
  }
}
```

**Targets endpoint with filter applied (200 OK):**

```json
{
  "data": [
    { "name": "products", "doc_count": 5 },
    { "name": "products-v2", "doc_count": 2 }
  ]
}
```
(The cluster also has `docs-articles` and `job-listings` indices on the same engine; they're excluded by the `products*` filter.)

**Empty / whitespace-only filter (422):**

```json
{
  "detail": {
    "error_code": "VALIDATION_ERROR",
    "message": "target_filter: must be a non-empty string after trimming whitespace, or omit the field entirely for no filter",
    "retryable": false
  }
}
```

(Python `fnmatch` is permissive — `*`, `?`, `[seq]`, `[!seq]`, and any literal string are all valid. There is no "invalid syntax" path that surfaces as 422; only length + non-emptiness are checked at registration.)

### 7.4 Enumerated value contracts

N/A — `target_filter` is a free-form string (max 256 chars, valid `fnmatch` glob). No enum, no allowlist, no dropdown values flowing back to the backend.

### 7.5 Error code catalog

No new error codes. The new field uses the existing `VALIDATION_ERROR` (422) code for syntactic invalidity.

## 9) Data model and state transitions

### New/changed entities

**Modified table: `clusters`**

- Add `target_filter VARCHAR(256) NULL` — operator-supplied glob pattern (Python `fnmatch.fnmatchcase` syntax: `*`, `?`, `[seq]`, `[!seq]`; NO brace expansion) that scopes `list_targets()` to matching index names. NULL = no filter (default + backward-compat for existing rows).

**Modified models:**

- `Cluster` ORM at [`backend/app/db/models/cluster.py:24`](../../../../backend/app/db/models/cluster.py#L24): add `target_filter: Mapped[str | None] = mapped_column(String(256), nullable=True)` after `notes`.
- `CreateClusterRequest` at [`backend/app/api/v1/schemas.py:50`](../../../../backend/app/api/v1/schemas.py#L50): add `target_filter: str | None = Field(default=None, min_length=1, max_length=256)` + a `@field_validator('target_filter')` that strips whitespace and rejects post-strip empty (no syntax validation — `fnmatch` accepts everything).
- `ClusterDetail` at [`schemas.py:94`](../../../../backend/app/api/v1/schemas.py#L94): add `target_filter: str | None = None`.
- `ClusterSummary` at [`schemas.py:109`](../../../../backend/app/api/v1/schemas.py#L109): add `target_filter: str | None = None`.
- `SearchAdapter` Protocol at [`backend/app/adapters/protocol.py:131`](../../../../backend/app/adapters/protocol.py#L131): signature change — `list_targets(self, *, request_id: str | None = None, target_filter: str | None = None) -> list[TargetInfo]`. Required so consumers typed against the Protocol can pass the kwarg.
- `StubAdapter` at [`backend/tests/integration/fixtures/stub_adapter.py:57`](../../../../backend/tests/integration/fixtures/stub_adapter.py#L57): accept the new kwarg (accept + ignore is fine — the stub's filtering isn't load-bearing for any test that uses it).

### Required invariants

- `target_filter` is either `NULL` or a non-empty (post-trim) string of length ≤256 chars. Empty string AND whitespace-only string MUST be rejected at the API layer (Pydantic `min_length=1` + validator's strip-then-reject). No glob-syntax validation — `fnmatch` is permissive; every non-empty string is a valid pattern.
- The pattern is applied AFTER the system-index `.` filter. Order is locked; no operator can re-expose system indices via the filter.
- Pattern matching MUST use `fnmatch.fnmatchcase()` (not `fnmatch.fnmatch()`) so behavior is platform-independent (Linux CI + macOS dev both produce case-sensitive match, matching ES's index naming semantics).
- Filter changes do NOT invalidate existing studies' `target` fields (no cascade — Locked Decision #4).

### State transitions

N/A — `target_filter` is set at registration and (for MVP) cannot be changed without DELETE + re-register. No state machine.

### Idempotency/replay behavior

N/A — registration is one-shot; the filter is just a column value.

## 10) Security, privacy, and compliance

- **Threats:**
  1. *Filter syntax used to crash the adapter* — N/A: Python `fnmatch` is permissive (no parse exception path). Every non-empty ≤256-char string is a valid pattern. The adapter call is `fnmatch.fnmatchcase(name, target_filter)`, which returns bool — no raise path.
  2. *Filter used to re-expose system indices* — order-of-operations guarantee: system-index `.` filter applies first; glob filter applies to the already-filtered subset. Operators cannot construct a filter that re-includes `.kibana_1` etc.
  3. *Filter exposes information about which indices exist on the engine* — N/A: the filter is OPERATOR-supplied; they already know what indices exist. The filter doesn't gain them new visibility, it just scopes what they see.
- **Controls:**
  - Pydantic length cap (256 chars) prevents pathological-length patterns.
  - `fnmatch.fnmatchcase` is a constant-time matcher over a bounded-length pattern; no ReDoS exposure.
  - Filter is stored as the trimmed value — leading/trailing whitespace is removed by the FR-2 validator, but no other normalization (no case-folding, no glob rewriting, no canonical-form transforms) is applied; matching is case-sensitive (FR-3).
- **Secrets/key handling:** N/A. The filter is non-secret operator config.
- **Auditability:** N/A — MVP1 has no `audit_log`. Documented MVP2+ event type: `CLUSTER_TARGET_FILTER_CHANGED`.
- **Data retention/deletion/export impact:** None — column is on the existing `clusters` row, no new tables, no PII.

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement:** Unchanged. The new field surfaces inside the existing `/clusters` register-cluster modal (reached from the "Register cluster" button on `/clusters` list).
- **Labeling taxonomy:** New strings — `"Target filter (optional)"` (label), `"Glob pattern restricting which indices appear in the target picker for this cluster. Example: products* matches every index starting with 'products'. Leave blank to show every user-facing index."` (helper text), `"No targets match filter \"<filter>\" on this cluster. Update the cluster's target filter to relax it."` (empty-state when filter excludes everything).
- **Content hierarchy:** Within the register-cluster modal: Cluster name → Engine type → Environment → Base URL → Auth kind → Credentials ref → Notes → **Target filter (new)** → Submit row. The new field is intentionally last because it's advanced / optional / used by power operators.
- **Progressive disclosure:** Field is always visible (no collapse). Helper text describes the syntax inline so operators don't need to consult docs.
- **Relationship to existing pages:** Extends the existing form. No new pages.

### Tooltips and contextual help

| Element | Text | Trigger | Placement |
|---|---|---|---|
| "Target filter" label | (none — inline helper text is sufficient) | — | — |
| Field helper text | `"Glob pattern restricting which indices appear in the target picker for this cluster. Example: products* matches every index starting with 'products'. Leave blank to show every user-facing index."` | always visible | below input |
| Empty-state (filter excludes everything) | `"No targets match filter \"<filter>\" on this cluster. Update the cluster's target filter to relax it."` | when `targets.data?.data.length === 0 && cluster.target_filter` | inside `<EntitySelect>` disabled trigger |

### Primary flows

1. **Operator registers a cluster with a filter:**
   - Open `/clusters` → click "Register cluster"
   - Fill name, engine, env, base URL, auth kind, credentials ref
   - Enter `products*` in Target filter
   - Click Submit → 201 → registered cluster appears in list with `target_filter="products*"`
2. **Operator opens create-study modal, picks the filtered cluster:**
   - From `/studies`, click "New study"
   - Pick `acme-products-prod` from cluster dropdown
   - Target dropdown loads via `GET /clusters/{id}/targets` — only `products` + `products-v2` appear (filter excluded `docs-articles` and `job-listings`)
3. **Filter-zero-match edge case:**
   - Operator registered cluster with `target_filter="non-matching-*"` accidentally
   - In the create-study modal: target dropdown shows `<EntitySelect>` empty-state: `"No targets match filter \"non-matching-*\" on this cluster. Update the cluster's target filter to relax it."`
   - Operator's recovery: DELETE the cluster + re-register without the bad filter (no PATCH affordance in MVP per Locked Decision #3)

### Edge/error flows

- **Operator submits invalid glob:** Pydantic 422 → toast `"target_filter: invalid glob pattern ... — fnmatch.translate raised: ..."` → form stays open, operator corrects + re-submits.
- **Operator submits empty-string filter:** Pydantic 422 → toast surfaces the constraint → operator clears the field entirely (null) or types a real pattern.
- **Operator submits whitespace-only filter:** Frontend trims → submits `null` → no error. (Server doesn't see whitespace.)
- **Operator registers cluster with filter, ES has zero matching indices today:** Registration succeeds (filter is syntactically valid; content-emptiness is not checked at registration). The empty-state surfaces only when the operator later opens the create-study modal.

## 12) Given/When/Then acceptance criteria

### AC-1: Migration round-trips on a populated DB

- **Given** the DB has 4 cluster rows from the demo seed (`acme-products-prod`, `corp-docs-search`, `news-search-staging`, `jobs-marketplace-prod`)
- **When** the operator runs `alembic upgrade head && alembic downgrade -1 && alembic upgrade head`
- **Then** all 4 rows survive, `target_filter` column is NULL on every row after the second upgrade, no data loss on the other 11 columns.

### AC-2: POST /clusters with valid filter (201)

- **Given** the operator sends `POST /api/v1/clusters` with body containing `"target_filter": "products*"` plus the other required fields
- **Then** the response is `201 Created` with `target_filter: "products*"` in the response body, and the row in `clusters` has `target_filter='products*'`.

### AC-3: POST /clusters with whitespace-only filter (422)

- **Given** the operator sends `POST /api/v1/clusters` with `"target_filter": "   "` (spaces only)
- **Then** the response is `422 VALIDATION_ERROR` envelope (validator strips, gets empty, raises). Pattern syntax itself is not validated — `fnmatch` is permissive, so there's no "invalid glob" path. The only structural validation is length + non-empty-after-trim.

### AC-4: POST /clusters with empty-string filter (422)

- **Given** the operator sends `POST /api/v1/clusters` with `"target_filter": ""`
- **Then** the response is `422 VALIDATION_ERROR` (Pydantic `min_length=1` semantics OR the validator's explicit check).

### AC-5: POST /clusters omitting filter defaults to NULL

- **Given** the operator sends `POST /api/v1/clusters` with NO `target_filter` field in the body
- **Then** the response is `201` with `target_filter: null`, and the DB row has `target_filter IS NULL`.

### AC-6: list_targets() applies filter (unit)

- **Given** a `_cat/indices` mock returns `[{"index": "products"}, {"index": "products-v2"}, {"index": "docs-articles"}, {"index": ".kibana_1"}]`
- **And** the adapter is called with `target_filter="products*"`
- **Then** the result is `[TargetInfo(name="products", ...), TargetInfo(name="products-v2", ...)]` — system index excluded, glob applied.
- **And** the implementation MUST use `fnmatch.fnmatchcase` (not `fnmatch.fnmatch`). Add a tertiary case: `target_filter="PRODUCTS*"` against the same mock must return `[]` (case-sensitive — `fnmatchcase` won't match lowercase `products` against uppercase pattern). If `fnmatch.fnmatch` were used instead, this assertion would pass on Linux CI but fail on macOS dev — surfacing the platform divergence directly.

### AC-7: list_targets() with NULL filter is regression-safe (unit)

- **Given** the same `_cat/indices` mock
- **And** the adapter is called with `target_filter=None`
- **Then** the result is `[TargetInfo(name="products"), TargetInfo(name="products-v2"), TargetInfo(name="docs-articles")]` — system index excluded, no glob applied. (Matches today's behavior; regression-tested.)

### AC-8: System-index filter wins over glob (unit)

- **Given** the same mock + `target_filter="*"`
- **Then** the result excludes `.kibana_1` (system filter applies first; `*` cannot re-expose it).

### AC-9: GET /clusters/{id}/targets passes the filter through (integration)

- **Given** a cluster is registered with `target_filter="products*"` against real ES
- **And** ES has indices `products`, `products-v2`, `docs-articles`, `job-listings`
- **When** the client issues `GET /api/v1/clusters/{cluster_id}/targets`
- **Then** the response `data` array contains only `products` and `products-v2` entries.

### AC-10: GET /clusters/{id} exposes target_filter (contract)

- **Given** a registered cluster with `target_filter="products*"`
- **When** the client issues `GET /api/v1/clusters/{cluster_id}`
- **Then** the response body includes `"target_filter": "products*"`.

### AC-11: Register-cluster modal submits target_filter when filled

- **Given** the operator fills `"products*"` in the new Target-filter input
- **When** they click Submit
- **Then** the `POST /clusters` request body contains `"target_filter": "products*"`.

### AC-12: Register-cluster modal converts whitespace-only to null

- **Given** the operator fills `"   "` (spaces only) in the Target-filter input
- **When** they click Submit
- **Then** the `POST /clusters` request body contains `"target_filter": null` (NOT the empty/whitespace string).

### AC-13: Create-study modal shows filter-aware empty-state

- **Given** a registered cluster with `target_filter="non-matching-*"` AND ES has no matching indices
- **When** the operator opens the create-study modal + picks that cluster
- **Then** the target dropdown's empty-state message reads `"No targets match filter \"non-matching-*\" on this cluster. To change the filter, delete and re-register the cluster — MVP1 has no in-place edit for cluster registrations."` (no PATCH endpoint exists per Locked Decision #3; the copy directs to the MVP1 recovery affordance).

### AC-14: Create-study modal preserves original empty-state when no filter is set

- **Given** a registered cluster with `target_filter=null` AND ES has no user-facing indices (only system indices)
- **When** the operator opens the create-study modal + picks that cluster
- **Then** the target dropdown's empty-state message reads `"No targets found on this cluster."` (the existing message — regression-safe).

## 13) Non-functional requirements

- **Performance:** Filter is applied client-side (Python loop over typically ≤200 rows). Each `fnmatch.fnmatch` call is O(pattern_length × name_length). Cumulative cost is sub-millisecond for realistic clusters.
- **Reliability:** No new SLO. Inherits the cluster + adapter reliability. Filter syntax errors caught at registration time; never raise at request time.
- **Operability:** Standard structlog request envelope; no new metrics. The cluster row stores the filter so operators can inspect it via `GET /clusters/{id}` or directly in the DB.
- **Accessibility/usability:** Optional input field; screen-reader-readable label; helper text below input (standard pattern in the existing register modal).

## 14) Test strategy requirements (spec-level)

- **Unit (`backend/tests/unit/`):**
  - `test_elastic_schema.py::TestListTargets` (extend): 4 new cases — `target_filter=None` regression; `target_filter="products*"` matches subset; `target_filter="nomatch*"` returns empty; `target_filter="*"` still excludes system indices (FR-3 order-of-operations).
  - `test_clusters_api_contract.py` or new `test_target_filter_validation.py`: 3 cases — invalid glob rejected; empty string rejected; valid pattern + max-length boundary accepted.
- **Integration (`backend/tests/integration/`):**
  - `test_clusters_api.py::TestTargetsEndpoint` (extend): 1 new case against real ES — register cluster with `target_filter="products*"`, seed 2 matching + 2 non-matching indices, assert response excludes non-matching.
  - Migration round-trip case: `alembic upgrade head → downgrade -1 → upgrade head` against a populated test DB.
- **Contract (`backend/tests/contract/`):**
  - `test_clusters_api_contract.py`: `target_filter` field present in `CreateClusterRequest`, `ClusterDetail`, `ClusterSummary` OpenAPI schemas.
- **Frontend unit (`ui/src/__tests__/`):**
  - `components/clusters/register-cluster-modal.test.tsx` (extend): 2 cases — fill filter + submit asserts request body; whitespace-only filter converts to null.
  - `components/studies/create-study-modal.test.tsx` (extend): 1 case — filter-aware empty-state message renders when `cluster.target_filter` is set + targets data is empty.
- **E2E (`ui/tests/e2e/`):**
  - None new. The dropdown happy-path E2E from PR #167 still works (with `target_filter=null` on the seeded clusters, behavior is unchanged).

**Coverage gate:** Backend coverage 80% (existing). New code paths covered by the tests above.

## 15) Documentation update requirements

- `docs/01_architecture/data-model.md` — `clusters` section adds the `target_filter` column with a one-line description.
- `docs/01_architecture/adapters.md` — `list_targets()` Protocol description adds the `target_filter` kwarg.
- `docs/01_architecture/api-conventions.md` — N/A (no new endpoint or error code).
- `docs/02_product/` → move feature folder to `implemented_features/<date>_feat_cluster_target_filter/` after merge.
- `docs/03_runbooks/` — N/A.
- `docs/04_security/` — N/A.
- `docs/05_quality/` — N/A.
- `state.md` — append to "Most recent meaningful changes" entry post-merge.
- `architecture.md` — N/A (no new top-level layer).
- `CLAUDE.md` — N/A.

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** None. Single-tenant MVP1 — ship on merge.
- **Migration/backfill expectations:** `0014_clusters_target_filter` adds the column with `nullable=True`, no backfill needed. All existing rows have `target_filter=NULL` after upgrade, which preserves today's behavior exactly.
- **Operational readiness gates:**
  - `make lint`, `make typecheck`, `make test` green
  - Round-trip migration verified
  - UI gates: `pnpm typecheck && pnpm lint && pnpm test && pnpm build`
- **Release gate:** CI green + Gemini Code Assist adjudicated + final GPT-5.5 review clean.

## 17) Traceability matrix

| FR ID | Acceptance Criteria | Planned stories | Test files | Docs |
|---|---|---|---|---|
| FR-1 (migration) | AC-1 | B1 | `test_clusters_api.py` migration case + manual round-trip | `data-model.md` |
| FR-2 (Pydantic + validator) | AC-2, AC-3, AC-4, AC-5 | B2 | `test_target_filter_validation.py` (or `test_clusters_api_contract.py`) | — |
| FR-3 (adapter filter) | AC-6, AC-7, AC-8, AC-9 | B3 | `test_elastic_schema.py::TestListTargets` + `test_clusters_api.py::TestTargetsEndpoint` | `adapters.md` |
| FR-4 (register modal field) | AC-11, AC-12 | F1 | `register-cluster-modal.test.tsx` | — |
| FR-5 (empty-state branching) | AC-13, AC-14 | F2 | `create-study-modal.test.tsx` | — |
| FR-6 (response models) | AC-10 | B2 (bundled with Pydantic changes) | `test_clusters_api_contract.py` | — |

## 18) Definition of feature done

- [ ] All AC-1 through AC-14 pass in CI.
- [ ] Unit + integration + contract layers green.
- [ ] Migration round-trip verified.
- [ ] Backend coverage gate (80%) satisfied.
- [ ] `data-model.md` + `adapters.md` updates merged.
- [ ] Gemini Code Assist findings adjudicated.
- [ ] Final GPT-5.5 review clean.
- [ ] No open questions in §19.

## 19) Open questions and decision log

### Open questions

None — all 4 forks were locked at preflight 2026-05-20 (per `idea.md`):
1. Glob syntax (not regex)
2. Client-side filtering in adapter (not engine-side)
3. Create-only filter for MVP (no PATCH; deferred to `chore_cluster_update_target_filter`)
4. No cascade validation (existing studies' `target` unaffected by filter changes)

### Decision log

- **2026-05-20** — `target_filter` stored as `VARCHAR(256) NULL`. Rationale: 256 chars is generous for realistic glob patterns; avoids the 64KB `TEXT` overhead; bounds API attack surface.
- **2026-05-20** — No glob-syntax validation at registration (cycle-1 GPT-5.5 review #1). Rationale: Python `fnmatch` is permissive — `fnmatch.translate()` accepts every non-empty string (unmatched `[` becomes literal, lone `?`/`*` match one/many chars, etc.). There's no "invalid syntax" raise path to wire into a 422. The user-meaningful validation is length + non-empty-after-trim. A bad pattern just doesn't match indices the operator expected — surfaces via the FR-5 empty-state message, not a 422.
- **2026-05-20** — Pattern matching uses `fnmatch.fnmatchcase()` not `fnmatch.fnmatch()` (cycle-1 GPT-5.5 review #3). Rationale: `fnmatch.fnmatch` calls `os.path.normcase`, which case-folds on macOS/Windows but not Linux — would produce environment-dependent behavior. ES index names are case-sensitive; `fnmatchcase` matches that semantics consistently across all platforms.
- **2026-05-20** — Helper text + spec drop brace-expansion examples (cycle-1 GPT-5.5 review #4). Rationale: Python `fnmatch` doesn't support `{a,b}` brace expansion (only bash does). Including `docs-{en,fr}-*` in examples would mislead operators into typing patterns that match literal braces. Supported syntax: `*`, `?`, `[seq]`, `[!seq]`. Operators who need OR-of-globs register two clusters.
- **2026-05-20** — `SearchAdapter` Protocol signature also updated (cycle-1 GPT-5.5 review #2). Rationale: extending only `ElasticAdapter` without the Protocol creates type-check drift + breaks `StubAdapter` callers when routers add the kwarg. Updating Protocol + StubAdapter + protocol test in the same story keeps the abstraction honest.
- **2026-05-20** — Filter applied AFTER system-index exclusion. Rationale: prevents operators from re-exposing `.kibana_1` etc. via `*`. Order is part of the security model (§10 Threat 2).
- **2026-05-20** — `target_filter` exposed on BOTH `ClusterDetail` AND `ClusterSummary`. Rationale: the create-study modal (FR-5) needs the field to branch the empty-state message; the modal already consumes `useClusters` (list endpoint) for the cluster picker, so the field must be on the summary.
- **2026-05-20** — Empty-state copy refers operators to DELETE + re-register, not "update the filter" (cycle-1 GPT-5.5 review #5). Rationale: the spec's own Locked Decision #3 says no PATCH for MVP. Copy that points operators at an unavailable action creates a dead-end UX. MVP4 follow-up `chore_cluster_update_target_filter` replaces this copy when PATCH ships.
- **2026-05-20** — Single-phase feature, no deferred phases. PATCH support lives as a separate `chore_cluster_update_target_filter` follow-up, not as a "phase 2" of this feature. Rationale: PATCH adds ~50 LOC backend + new UI surface + new tests — that's its own feature scope, not a tail-end of this one.
