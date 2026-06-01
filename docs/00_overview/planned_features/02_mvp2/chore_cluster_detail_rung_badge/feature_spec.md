# Feature Specification — chore_cluster_detail_rung_badge

**Date:** 2026-06-01
**Status:** Draft (post-GPT-5.5 convergence)
**Owners:** Engineering — RelyLoop frontend
**Related docs:**
- [`idea.md`](idea.md) — origin + verified preflight
- [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md) — cluster-detail page conventions
- [`docs/00_overview/planned_features/02_mvp2/feat_ubi_llm_study_comparison/feature_spec.md`](../feat_ubi_llm_study_comparison/feature_spec.md) §3 — split-out source
- [`docs/00_overview/implemented_features/2026_05_30_feat_demo_ubi_study_comparison/feature_spec.md`](../../../implemented_features/2026_05_30_feat_demo_ubi_study_comparison/feature_spec.md) §7 FR-7 #3 — chip placement to be corrected post-ship

---

## 1) Purpose

- **Problem:** An operator viewing `/clusters/[id]` cannot see at a glance whether the cluster has UBI-ready behavioral data. The `<UbiRungBadge>` ([`ui/src/components/clusters/ubi-rung-badge.tsx`](../../../../ui/src/components/clusters/ubi-rung-badge.tsx)) renders the rung today only inside the generate-judgments dialog, because the readiness endpoint requires `query_set_id + target` context the cluster-detail page does not have. As a consequence, the Phase-1 `feat_demo_ubi_study_comparison` FR-7 #3 synthetic-data disclaimer chip — specified to sit "adjacent to the `<UbiRungBadge>`" on the cluster-detail page — currently lives next to the cluster **name** as a workaround.
- **Outcome:** The cluster-detail page surfaces a `<UbiRungBadge>` for the cluster, scoped by a user-selected (or auto-seeded) query set + target. The Phase-1 synthetic-data chip relocates adjacent to the rendered badge, restoring the placement intent of `feat_demo_ubi_study_comparison` FR-7 #3 without re-opening that feature's spec for a wording patch.
- **Non-goal:** This feature is a **read-only, frontend-only** wiring chore. It does not modify the readiness endpoint, does not change the badge component, does not introduce new wire enums, does not add a backend hint endpoint, and does not generate judgments. It also does not redesign the cluster-detail layout — the new card slots into the existing page composition. **One existing UI hook is touched** — `ui/src/lib/api/ubi.ts` `useUbiReadiness` gains `placeholderData: keepPreviousData` (one-line change; D-15) to satisfy AC-8.

## 2) Current state audit

### Existing implementations

| File | What it does | API / dependency | Notes from audit |
|---|---|---|---|
| [`ui/src/components/clusters/ubi-rung-badge.tsx`](../../../../ui/src/components/clusters/ubi-rung-badge.tsx) (49 lines) | Text-only badge rendering one of four `UbiReadinessRung` labels (`rung_0` → `rung_3`) + glossary popover keyed `cluster.ubi_readiness`. | Pure presentational; props `{ rung: UbiReadinessRung }`. | Single variant — the context-free "snapshot" variant was removed in cycle 3 of `feat_ubi_judgments` (`readiness-snapshot-badge-contract-drift`). Has `data-testid="ubi-rung-badge"` + `data-rung={rung}`. |
| [`ui/src/components/clusters/cluster-detail-summary.tsx`](../../../../ui/src/components/clusters/cluster-detail-summary.tsx) (87 lines) | Card with cluster name + engine + environment + auth + base URL + target_filter. **Hosts the Phase-1 synthetic-data chip** at lines 23–30, gated on `isDemoSyntheticUbiClusterName(cluster.name)`, rendering `<DemoBadge variant="synthetic-ubi" />` next to `cluster.name`. | Reads `ClusterDetail` shape from `useCluster(id)`. | The chip placement next to the name is the documented workaround; this chore relocates it. |
| [`ui/src/app/clusters/[id]/page.tsx`](../../../../ui/src/app/clusters/[id]/page.tsx) (55 lines) | Composes `ClusterDetailSummary` → `ClusterActionBar` → `ClusterDetailIndicesCard` → "Studies using this cluster" card. | Uses `DetailPageShell` for loading + 404 envelopes. | New `ClusterDetailUbiReadinessCard` slots into this composition. |
| [`ui/src/lib/api/ubi.ts`](../../../../ui/src/lib/api/ubi.ts:72) `useUbiReadiness(clusterId, querySetId, target)` | TanStack hook that GETs `/api/v1/clusters/{id}/ubi-readiness?query_set_id=…&target=…`. | 60 s `staleTime` matching the backend Redis cache; returns null until all three params present; degrades to `rung_0` on 404/503. | **One minimal patch** — add `placeholderData: keepPreviousData` (import from `@tanstack/react-query`) to the `useQuery` options so badge values persist across `(query_set_id, target)` edits per AC-8 / D-15. The existing dialog consumer (generate-judgments dialog) is unaffected because its query key only changes when the user re-opens the dialog with a different `(cluster, query_set, target)` triple, where preserving the previous value across opens is a harmless improvement, not a regression. |
| [`backend/app/api/v1/clusters.py:412-465`](../../../../backend/app/api/v1/clusters.py) `GET /clusters/{cluster_id}/ubi-readiness` | Required query params `query_set_id` (`min_length=1 max_length=36`) + `target` (`min_length=1 max_length=256`). | Error codes: `404 CLUSTER_NOT_FOUND`, `404 QUERY_SET_NOT_FOUND`, `422 VALIDATION_ERROR` (missing params **and** query_set/cluster mismatch), `503 CLUSTER_UNREACHABLE`. | Endpoint enforces that `query_set.cluster_id == cluster_id`; the frontend's cluster-scoped picker prevents this 422 from being reachable in practice. |
| [`ui/src/lib/api/query-sets.ts:52`](../../../../ui/src/lib/api/query-sets.ts) `useQuerySets({ cluster_id })` | Cursor-paginated list scoped by cluster_id; returns `QuerySetSummary[]` with `{ id, name, cluster_id, created_at }` ([`backend/app/api/v1/schemas.py:510-516`](../../../../backend/app/api/v1/schemas.py)). | The Summary omits `query_count` (intentional — N+1 avoidance at list time); we don't need it. | Sort key `QuerySetSortKey` defaults to newest-first via cursor; the picker can render the API order or sort client-side by `created_at` desc. |
| [`ui/src/components/clusters/ubi-onramp-nudge.tsx`](../../../../ui/src/components/clusters/ubi-onramp-nudge.tsx) | Rung_0 nudge card — engine-aware copy + a "What is UBI?" CTA. Consumed inside the generate-judgments dialog today. | Pure presentational; takes `engine: EngineType`. | This spec does NOT mount the on-ramp nudge on cluster-detail — that is `feat_ubi_judgments` FR-8 territory and out of scope here (D-4 below). |
| [`ui/src/lib/enums.ts:158-160`](../../../../ui/src/lib/enums.ts) `UBI_READINESS_RUNG_VALUES` | `['rung_0', 'rung_1', 'rung_2', 'rung_3']` with source-of-truth comment. | Wire-grounded to `backend/app/api/v1/schemas.py UbiReadinessRungWire`. | No new enum added by this chore. |
| [`ui/src/components/common/demo-badge.tsx`](../../../../ui/src/components/common/demo-badge.tsx) `DemoBadge variant="synthetic-ubi"` | Renders the "Synthetic demo data" chip with `data-testid="demo-badge-synthetic-ubi"`. | Pure presentational. | Re-used at the new placement. |
| [`ui/src/lib/glossary.ts`](../../../../ui/src/lib/glossary.ts) key `cluster.ubi_readiness` | Long-form description of the four rungs. | Consumed by the badge's `<HelpPopover glossaryKey>`. | Re-used unchanged. |

### Navigation and link impact

| Source file | Current link target | New link target |
|---|---|---|
| n/a | n/a | No URL routes added, removed, or renamed. The card mounts inside `/clusters/[id]`; no deep-link to the picker state is in scope (D-7 below). |

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `ui/src/__tests__/components/clusters/cluster-detail-summary*.test.tsx` (if any) | `DemoBadge variant="synthetic-ubi"` placement adjacent to `cluster.name` | grep at impl time | Update assertions: the chip is removed from `ClusterDetailSummary` and is asserted to appear inside the new readiness card adjacent to `<UbiRungBadge>`. If no such test exists today, add a vitest spec for both pre- and post-conditions. |
| Phase-1 `feat_demo_ubi_study_comparison` E2E (`ui/tests/e2e/demo-ubi-comparison*.spec.ts` if extant) | `demo-badge-synthetic-ubi` assertion on `/clusters/{id}` | grep at impl time | Re-anchor the selector to the new placement; assertion text/value unchanged. |
| `ui/src/__tests__/components/clusters/ubi-rung-badge*.test.tsx` | `data-testid="ubi-rung-badge"` | unknown | No change (component unchanged). |
| `backend/tests/contract/clusters/test_ubi_readiness*.py` | endpoint shape | n/a | No change (backend unchanged). |

Concrete grep targets handed to the implementation plan: `data-testid="demo-badge-synthetic-ubi"`, `data-testid="ubi-rung-badge"`, `isDemoSyntheticUbiClusterName`, `cluster-detail-summary`.

### Existing behaviors affected by scope change

- **Synthetic-data chip placement:** Current: rendered inside `<ClusterDetailSummary>`'s `<CardTitle>` next to `cluster.name`. New: rendered inside the new `<ClusterDetailUbiReadinessCard>` adjacent to `<UbiRungBadge>`. Decision needed: **no** — locked in D-1.
- **`<UbiRungBadge>` consumption sites:** Current: dialog-only (generate-judgments). New: dialog AND `/clusters/[id]` (the new card). Decision needed: **no** — both call sites pass the same single-prop interface; component is unchanged.
- **`useUbiReadiness` consumption sites:** Current: one (generate-judgments dialog). New: two (dialog + readiness card). Hook semantics (null-until-all-three-params, 404/503 → `rung_0` graceful degrade) are reused unchanged for both 404/503 behavior and the `staleTime`. The **one-line** patch adds `placeholderData: keepPreviousData` to the `useQuery` options inside `ui/src/lib/api/ubi.ts` so the badge value persists across `(query_set_id, target)` edits per AC-8 / D-15. The existing dialog consumer is unaffected — its query key only changes when the dialog is re-opened with a different `(cluster, query_set, target)` triple, and preserving the previous resolved value across re-opens is harmless (no UX regression).
- **`feat_demo_ubi_study_comparison` FR-7 #3 wording:** That spec's prose says "adjacent to the `<UbiRungBadge>`"; once this chore ships, the wording becomes true. We do not rewrite the implemented-feature spec — those are immutable post-merge — but §15 documents the doc-update touchpoint (the runbook / arch-doc that summarizes chip placement, if any). Decision needed: **no** — the implemented-feature spec is left untouched per "no legacy preservation" inverse: ship the live behavior to match the prose, don't rewrite prose to match historical workarounds.

---

## 3) Scope

### In scope

- A new `ClusterDetailUbiReadinessCard` component that mounts inside `/clusters/[id]`, between `ClusterActionBar` and `ClusterDetailIndicesCard` (D-2 below).
- The card renders one of four states (FR-1 / FR-4):
  1. **Empty state — no query sets yet:** a short "Create a query set to check UBI readiness" hint with a Link to `/query-sets/new?cluster_id={id}` (or the equivalent existing create flow; the impl plan resolves the exact URL).
  2. **Pickers visible (no auto-seed):** a query-set `<select>` (populated via `useQuerySets({ cluster_id })`) + a free-form `<input>` for target (placeholder seeded from `cluster.target_filter` when present). No badge until both are set.
  3. **Auto-seeded:** when the cluster has exactly one query set AND a non-null `cluster.target_filter`, both inputs initialize to that pair on mount; the badge renders immediately with that pair (still editable).
  4. **Resolved:** `<UbiRungBadge rung={readiness.rung} />` adjacent to the synthetic-data chip when `isDemoSyntheticUbiClusterName(cluster.name)` is true.
- Relocate the existing `<DemoBadge variant="synthetic-ubi" />` from `ClusterDetailSummary` to the new card, keeping the same `isDemoSyntheticUbiClusterName(cluster.name)` gate.
- Loading / error UX for the readiness call: skeleton on first fetch; on 404/503 fallback the hook degrades to `rung_0` (existing behavior) and the card renders `rung_0` with a single generic "Couldn't refresh UBI status (cluster unreachable or query set missing)" caption (FR-5). The frontend cannot distinguish 404 from 503 because the hook returns the same `{rung_0, covered_pairs_pct:null, head_covered:null}` shape for both ([`ui/src/lib/api/ubi.ts:89-101`](../../../../ui/src/lib/api/ubi.ts)); we use a single caption keyed off `covered_pairs_pct === null` rather than expanding the hook's return contract (D-10).
- Glossary entry `cluster.ubi_readiness` is re-used unchanged via `<HelpPopover>` inside the badge — no new glossary key required.

### Out of scope

- **Backend changes.** No endpoint, schema, migration, or service function is added or modified. The readiness endpoint, the badge component, and `useQuerySets` already exist. **Decision: locked — D-3.**
- **A new "default query set + target" backend hint endpoint.** The frontend resolves the auto-seed locally from `useQuerySets({ cluster_id }).data` + `cluster.target_filter`. A server-side hint would duplicate that knowledge with no caller. **Decision: locked — D-3.**
- **Mounting `<UbiOnrampNudge>` on `/clusters/[id]`.** That card belongs to `feat_ubi_judgments` FR-8 and to the generate-judgments-dialog surface — adding it to cluster-detail would re-open the on-ramp surface design. The new readiness card surfaces the rung; the nudge stays in the dialog. **Decision: locked — D-4.**
- **Deep-linking the picker state via URL params** (e.g., `/clusters/{id}?query_set_id=…&target=…`). Read-only card; no URL contract. **Decision: locked — D-7.**
- **Editing `feat_demo_ubi_study_comparison`'s shipped feature spec.** Implemented-feature specs are immutable post-merge. The chip relocation makes the prose accurate; no historical edit. **Decision: locked — D-1.**
- **Adding a target picker that enumerates indices from the engine adapter** (e.g., calling `list_targets` on cluster register). The endpoint accepts free-form text; the cluster's `target_filter` is the natural seed. An index picker UI is its own feature and would touch the adapter on every page load. **Decision: locked — D-5.**
- **Refactoring the badge into a context-aware shape.** Keep `<UbiRungBadge rung={…} />` as a pure rung-renderer; the new card holds the data-fetching logic. **Decision: locked — D-6.**

### API convention check

- **Endpoint prefix:** `/api/v1/<resource>` per [`api-conventions.md`](../../../01_architecture/api-conventions.md). The single endpoint consumed here (`GET /api/v1/clusters/{cluster_id}/ubi-readiness`) follows that convention — already in production.
- **Router namespace:** `backend/app/api/v1/clusters.py` — already exists; no router changes.
- **HTTP methods:** N/A (frontend-only chore).
- **Non-auth error envelope shape:** `{ "detail": { "error_code": "<CODE>", "message": "<human>", "retryable": <bool> } }` per `api-conventions.md`. The frontend already handles this shape in `ApiError`; the readiness hook intercepts only 404/503 for graceful degradation.
- **Auth error shape:** N/A — single-tenant, no auth surface through MVP3.

### Phase boundaries

**Single-phase.** This is a small, frontend-only chore (one new component + one chip relocation). There is no deferred Phase 2. No `phase2_idea.md` is created.

## 4) Product principles and constraints

- **Read-only.** The card surfaces information; it never mutates server state. No POST/PUT/PATCH/DELETE.
- **Engine-neutral.** The card uses the same readiness endpoint for ES, OpenSearch, and Solr; no per-engine branching on the frontend. The hook's 60 s `staleTime` mirrors backend cache TTL for all three.
- **Source-of-truth-grounded enums.** The only wire enum surfaced is `UbiReadinessRung`, already imported from `ui/src/lib/enums.ts` with its `// Values must match backend/app/api/v1/schemas.py UbiReadinessRungWire.` comment (CLAUDE.md "Enumerated Value Contract Discipline").
- **Graceful degradation under cluster failure.** On 503 from the readiness endpoint the hook returns `rung_0` so the dialog method-picker stays functional; the new card surfaces the same `rung_0` with an explanatory caption rather than an error toast or empty state.
- **Reuse over abstraction.** No new shared primitive is extracted. The card composes `<Card>`, `<UbiRungBadge>`, `<DemoBadge>`, and standard form controls.
- **No URL contract.** Picker state is component-local React state; no `useSearchParams` round-tripping.

### Anti-patterns

- **Do not** introduce a backend "best default query set + target for cluster" hint endpoint — it would duplicate the frontend's local computation and add a network round-trip with no second caller.
- **Do not** add a new variant of `<UbiRungBadge>` (e.g., a context-aware one that takes `(clusterId, querySetId, target)` and fetches internally) — that re-introduces the very pattern cycle-3 of `feat_ubi_judgments` removed. The badge stays a pure rung-renderer; data-fetching lives in the card.
- **Do not** call `useUbiReadiness` from inside `<UbiRungBadge>` — keep the hook call at the card level so the component remains testable with a single `rung` prop and re-usable wherever a rung is already known.
- **Do not** invent values for the rung enum — import `UBI_READINESS_RUNG_VALUES` / `UbiReadinessRung` from `@/lib/enums`.
- **Do not** re-introduce the chip at the old placement after relocation. Replace, do not duplicate; vitest asserts the chip is absent from `ClusterDetailSummary`'s rendered output.
- **Do not** mount the on-ramp nudge on `/clusters/[id]` — out of scope (D-4).
- **Do not** deep-link picker state in the URL — out of scope (D-7).
- **Do not** call `list_targets` on the engine adapter to enumerate index choices — the target is free-form, seeded from `cluster.target_filter`.
- **Do not** delete `isDemoSyntheticUbiClusterName` from `ClusterDetailSummary`'s imports if it's used elsewhere. Verify at edit time.

## 5) Assumptions and dependencies

- **`GET /api/v1/clusters/{cluster_id}/ubi-readiness`** ([`backend/app/api/v1/clusters.py:412-465`](../../../../backend/app/api/v1/clusters.py)) — required.
  - Why required: data source for the rung value.
  - Status: implemented (`feat_ubi_judgments`, shipped pre-MVP2).
  - Risk if missing: N/A — already in production.
- **`useUbiReadiness` TanStack hook** ([`ui/src/lib/api/ubi.ts:72`](../../../../ui/src/lib/api/ubi.ts)) — required.
  - Status: implemented.
- **`useQuerySets({ cluster_id })`** ([`ui/src/lib/api/query-sets.ts:52`](../../../../ui/src/lib/api/query-sets.ts)) — required.
  - Status: implemented; cluster_id filter active.
- **`<UbiRungBadge>`** ([`ui/src/components/clusters/ubi-rung-badge.tsx`](../../../../ui/src/components/clusters/ubi-rung-badge.tsx)) — required.
  - Status: implemented; single-prop interface.
- **`<DemoBadge variant="synthetic-ubi">`** + **`isDemoSyntheticUbiClusterName`** — required (relocation source).
  - Status: implemented (Phase-1 `feat_demo_ubi_study_comparison`, PR #320).
- **Glossary key `cluster.ubi_readiness`** — required.
  - Status: implemented; consumed via `<HelpPopover>` inside the badge.
- **Soft coordination — `feat_ubi_llm_study_comparison`:** independent. The comparison view does not depend on this chore; this chore does not depend on the comparison view. **Status:** sibling spec (`02_mvp2/feat_ubi_llm_study_comparison/feature_spec.md`) has already declared the split in its §3 ("Out of scope") and §19 (decision-log 2026-05-31). No coordination action required.

## 6) Actors and roles

- **Primary actor:** Relevance Engineer (the operator viewing `/clusters/[id]`).
- **Role model:** N/A — RelyLoop is single-tenant + no auth through MVP3 per [`tech-stack.md` "Canonical release matrix"](../../../01_architecture/tech-stack.md).

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — read-only view. `audit_log` lands at MVP3 ([`data-model.md` §"Forthcoming: audit_log"](../../../01_architecture/data-model.md)).

## 7) Functional requirements

### FR-1: Mount `<ClusterDetailUbiReadinessCard>` inside `/clusters/[id]`

- Requirement:
  - The system **MUST** render a new `<ClusterDetailUbiReadinessCard cluster={cluster} />` component inside `ClusterDetailView` ([`ui/src/app/clusters/[id]/page.tsx`](../../../../ui/src/app/clusters/[id]/page.tsx)), positioned **between** `<ClusterActionBar>` and `<ClusterDetailIndicesCard>` (D-2). The card is always present for non-deleted clusters; its **interior** chooses among empty / pickers / auto-seeded / resolved states per FR-3.
  - The card **MUST** be a client component (`'use client'`) — it consumes TanStack hooks.
- Notes: The card is unconditionally mounted so its empty-state hint is also discoverable on a freshly-registered cluster. The interior state choice handles "no query sets" / "no auto-seed candidate" / "resolved" branches.

### FR-2: Query-set picker is cluster-scoped via `useQuerySets({ cluster_id })`

- Requirement:
  - The picker **MUST** populate from a dedicated `useQuerySets({ cluster_id: cluster.id, limit: PICKER_LIMIT })` call where `PICKER_LIMIT = 50` (matches the project's default page size per [`api-conventions.md`](../../../01_architecture/api-conventions.md) §"Pagination"). The picker is **separate** from the auto-seed proof call (FR-4) — they serve different purposes (full enumeration vs single-cardinality proof) and using one call for both would either truncate the picker (D-14a) or waste bandwidth on a full scan when only single-cardinality matters.
  - When the picker call's response has `has_more === true`, the picker **MUST** show a footer hint "Showing first 50 query sets. [Browse all](/query-sets?cluster_id=…)" — the link points the operator at `/query-sets?cluster_id={id}` where the existing `?q=` name-substring filter lives. The card does NOT implement cursor pagination inside the picker itself (D-14b — the picker is a `<Select>`, not a list page; the operator picks one query set, not multiple, so deep filtering belongs on the list page).
  - The picker **MUST NOT** call the readiness endpoint until a query set is selected (or auto-seeded).
  - The picker **MUST** show the query set's `name` as the option label and use the `id` as the wire value.
  - The picker **MUST** disable submit / readiness fetch when the underlying `useQuerySets` query is loading or has errored.
- Notes: `QuerySetSummary` already carries `(id, name, cluster_id, created_at)` ([`backend/app/api/v1/schemas.py:510-516`](../../../../backend/app/api/v1/schemas.py)); no additional fields are required server-side. React Query's request-deduping caches the response by query key; the two `useQuerySets` calls in the card (FR-2 picker `limit=50` and FR-4 auto-seed `limit=2`) have distinct cache keys and are intentionally separate.

### FR-3: Target input is free-form, seeded from `cluster.target_filter`

- Requirement:
  - The target control **MUST** be a free-form text `<input>` with `placeholder` equal to `cluster.target_filter` when non-null and equal to "index or collection name" otherwise.
  - When `cluster.target_filter` is non-null AND the auto-seed condition holds (FR-4), the input **MUST** initialize with that value (not just placeholder); otherwise the input **MUST** start empty.
  - The input **MUST** trim leading/trailing whitespace before issuing the readiness call.
  - The input **MUST NOT** issue a readiness call until both the query set is selected AND the target is non-empty after trim.
  - The system **MUST** enforce a client-side length cap matching the backend's `max_length=256` constraint ([`backend/app/api/v1/clusters.py:420`](../../../../backend/app/api/v1/clusters.py)).
- Notes: The target is engine-specific (index name on ES/OpenSearch, collection name on Solr) but the endpoint treats it as opaque text; no per-engine validation client-side.

### FR-4: Auto-seed when both signals point at a single obvious candidate

- Requirement:
  - The card **MUST** make a **separate** `useQuerySets({ cluster_id, limit: 2 })` call dedicated to the auto-seed proof (in addition to the FR-2 picker call at `limit: 50`). The two calls have distinct React Query cache keys; React Query handles deduping if a future change ever collapses the limits.
  - On first mount, the system **MUST** auto-seed when **all three** of these hold against the settled auto-seed-call response: (a) `data.data.length === 1`, (b) `data.has_more === false`, AND (c) `cluster.target_filter` is non-null and non-empty after `trim()`. The picker then initializes to that query set's id; the target input initializes to `cluster.target_filter`.
  - In any other settled state (zero rows; ≥2 rows; one row but `has_more === true`; one row but `target_filter` null), the system **MUST** start with both controls unselected/empty.
- Notes: Requesting `limit: 2` lets the auto-seed proof work without scanning the whole paginated list — a single page can contain at most one row AND `has_more` flips to `true` if a second exists. (`useQuerySets` returns `QuerySetListResponse & { totalCount }` from the `X-Total-Count` header per [`ui/src/lib/api/query-sets.ts:52-65`](../../../../ui/src/lib/api/query-sets.ts); we use `has_more` rather than `totalCount` because `X-Total-Count` is a separate count column and `has_more` is the in-page authoritative signal.) Demo clusters (each has one query set + a populated `target_filter`) auto-seed zero-click. Multi-query-set clusters are intentionally not auto-picked — we avoid "newest" / "most recent" heuristics that can quietly select the wrong context.

### FR-5: Resolved-state rendering uses `<UbiRungBadge>` + relocated synthetic-data chip

- Requirement:
  - The card **MUST** gate badge/chip rendering on **both** (a) `useUbiReadiness(...)` returning a non-null response **and** (b) the *current* picker state still being valid — i.e., `querySetId` is non-empty and `target.trim()` is non-empty. With `placeholderData: keepPreviousData` (D-15), the hook continues to hold the prior response after the operator clears either control, so a `response !== null` gate alone would leak a stale badge for an invalid current selection. The two-condition gate prevents that leak (D-16).
  - Once both gates pass, the card **MUST** render `<UbiRungBadge rung={response.rung} />`.
  - When `isDemoSyntheticUbiClusterName(cluster.name)` is true, the card **MUST** render `<DemoBadge variant="synthetic-ubi" />` **adjacent to** the badge (same horizontal row, gap-2 spacing).
  - The card **MUST NOT** render the chip in `<ClusterDetailSummary>` anymore (relocation, not duplication).
  - The card **MUST** show the four labels and tooltip from the existing `<UbiRungBadge>` + its `<HelpPopover glossaryKey="cluster.ubi_readiness">` — no new label / glossary text.
  - When the readiness call settled to `rung_0` from the hook's fallback path (signaled by `covered_pairs_pct === null && head_covered === null`), the card **MUST** show a small muted caption "Couldn't refresh UBI status (cluster unreachable or query set missing)" next to the badge. The caption is the **same** for both 404 and 503 — the hook does not expose which (D-10).
- Notes: The hook already returns `{ rung: 'rung_0', covered_pairs_pct: null, head_covered: null, checked_at: <now> }` on both 404 and 503 ([`ui/src/lib/api/ubi.ts:89-101`](../../../../ui/src/lib/api/ubi.ts)); the caption is gated on `covered_pairs_pct === null && rung === 'rung_0' && head_covered === null`. A genuine `rung_0` from real classification (no UBI traffic) carries non-null `covered_pairs_pct` (typically 0) — the gate distinguishes "checked, zero coverage" from "fallback."

### FR-6: Empty state when the cluster has no query sets

- Requirement:
  - Let `pickerResponse = pickerQuery.data` (the `QuerySetListResponse & { totalCount }` from the FR-2 picker call). When `pickerQuery.status === 'success'` AND `pickerResponse.data.length === 0`, the card **MUST** show the text "Create a query set to check UBI readiness for this cluster." followed by a `<Link>` to the existing query-set create flow scoped to this cluster.
  - The empty state **MUST NOT** render a `rung_0` badge (a `rung_0` badge means "checked, no UBI data," not "never checked" — Q-3 lock).
- Notes: The phrasing `pickerResponse.data.length === 0` is intentional — `pickerQuery.data` is the TanStack `data` field which holds the **response body**, whose `data` field is the **row array**. The auto-seed proof in FR-4 uses the same nesting (`data.data.length === 1`). The implementation plan resolves the exact create-flow URL (likely `/query-sets/new?cluster_id={id}` or whatever the existing flow accepts); both the URL and the text live in the impl plan, not here.

### FR-7: Loading and error UX

- Requirement:
  - While `useUbiReadiness` is in-flight (status `pending`, after enable), the card **MUST** show a small inline skeleton in place of the badge.
  - On `404 QUERY_SET_NOT_FOUND` (unexpected since the picker is cluster-scoped), the hook degrades to `rung_0` per existing behavior; the card renders `rung_0` with the same unified caption from FR-5 ("Couldn't refresh UBI status (cluster unreachable or query set missing)"). The frontend treats 404 and 503 identically because the hook does not expose which condition fired (D-10).
  - On unrecognized error codes (anything other than 404/503), the hook re-throws; the card surfaces a small inline error `<span>` "Couldn't load UBI readiness" with a one-click retry that invalidates the React Query cache for that key.
- Notes: We do not toast — the failure is local to the card; the rest of the page (summary, indices, studies) is independent.

### FR-8: Vitest + Playwright coverage matches the new structure

- Requirement:
  - The system **MUST** ship a vitest spec for `<ClusterDetailUbiReadinessCard>` covering all four states (empty / pickers-unset / auto-seeded / resolved with chip on demo clusters), the 503 caption, and the chip's absence from `ClusterDetailSummary`.
  - The system **MUST** ship a Playwright spec exercising the resolved state on the seeded `acme-products-prod` (synthetic-UBI) demo cluster: visit `/clusters/{id}` → badge reads a non-`rung_0` value → chip is present adjacent to badge → chip is **not** present next to cluster name.
- Notes: Mocking policy — the Playwright spec must use a real backend per CLAUDE.md "E2E Testing Rules" (no `page.route()` mocking).

## 8) API and data contract baseline

### 7.1 Endpoint surface

No new endpoints. The chore consumes one existing endpoint:

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `GET` | `/api/v1/clusters/{cluster_id}/ubi-readiness?query_set_id=<id>&target=<text>` | Read the rung for `(cluster, query_set, target)` | `404 CLUSTER_NOT_FOUND`, `404 QUERY_SET_NOT_FOUND`, `422 VALIDATION_ERROR`, `503 CLUSTER_UNREACHABLE` |

### 7.2 Contract rules

- The frontend **MUST NOT** issue the GET until both `query_set_id` and `target` are non-empty (avoids spurious 422s).
- The hook intercepts only `404` and `503` for `rung_0` degradation; all other error codes re-throw.
- No new error codes are introduced. No new response shapes.

### 7.3 Response examples

Reproduced from `feat_ubi_judgments` shipped spec; no new shapes added.

Success (`200`):

```json
{
  "rung": "rung_3",
  "covered_pairs_pct": 0.87,
  "head_covered": true,
  "checked_at": "2026-06-01T15:42:11Z"
}
```

Cluster unreachable (`503`), envelope per `api-conventions.md`:

```json
{
  "detail": {
    "error_code": "CLUSTER_UNREACHABLE",
    "message": "cluster <id> not reachable from RelyLoop",
    "retryable": true
  }
}
```

Query-set / cluster mismatch (`422`) — defensive only; the cluster-scoped picker should prevent this in practice:

```json
{
  "detail": {
    "error_code": "VALIDATION_ERROR",
    "message": "query_set <qs-id> belongs to cluster '<other-id>', not '<this-id>'",
    "retryable": false
  }
}
```

### 7.4 Enumerated value contracts

| Field | Accepted values (exact) | Backend source of truth | Frontend call site(s) |
|---|---|---|---|
| `UbiReadinessResponse.rung` | `rung_0`, `rung_1`, `rung_2`, `rung_3` | `backend/app/api/v1/schemas.py` `UbiReadinessRungWire` Literal | `ui/src/lib/enums.ts:158-160` `UBI_READINESS_RUNG_VALUES` (already imported by the badge) |

No new option lists are introduced. The query-set `<select>` lists rows by `id` (not enum literals), and the target input is free-form text (not an allowlisted enum) — both fall outside §7.4 per the rubric.

### 7.5 Error code catalog

No new error codes. The chore consumes the existing `feat_ubi_judgments` codes (`CLUSTER_NOT_FOUND`, `QUERY_SET_NOT_FOUND`, `VALIDATION_ERROR`, `CLUSTER_UNREACHABLE`) without modification.

## 9) Data model and state transitions

### New/changed entities

None. No migration. No ORM-model changes. No new columns.

### Required invariants

- The synthetic-data chip on `/clusters/[id]` renders **exactly once** per visit — either next to the rung badge (post-chore) and nowhere else, or not at all if `isDemoSyntheticUbiClusterName(cluster.name)` is false. Vitest enforces "no duplicate" by asserting `getAllByTestId('demo-badge-synthetic-ubi')` returns length ≤ 1 on the cluster-detail render.

### State transitions

Card interior local state machine (component-local React state, no server side):

- `loading_query_sets` → `empty` (zero query sets) | `idle_pickers` (≥1 query set, no auto-seed candidate) | `auto_seeded` (one query set + non-null `target_filter`).
- `idle_pickers` → `armed` (both controls populated) → `loading_rung` → `resolved` | `fallback_503` | `inline_error`.
- `auto_seeded` → `loading_rung` (immediate) → `resolved` | `fallback_503` | `inline_error`.
- `resolved` / `fallback_503` / `inline_error` may transition back to `armed` on any picker/input edit; the readiness call re-fires after a 200 ms debounce on the target input.

### Idempotency/replay behavior

Not applicable — read-only GETs with a 60 s server cache + 60 s client `staleTime`; back-to-back card opens hit the React Query cache, not the network. No event-driven path.

## 10) Security, privacy, and compliance

- **Threats:**
  1. Information disclosure — the rung label reveals coarse-grained UBI traffic presence. **Control:** the underlying endpoint already gates on cluster ownership (single-tenant install — no cross-tenant leakage possible until MVP4 auth lands).
  2. Synthetic-data confusion — an operator viewing a demo cluster might infer real UBI traffic. **Control:** the `<DemoBadge variant="synthetic-ubi">` chip relocates adjacent to the badge so the disclaimer is co-located with the claim it disclaims.
  3. Open-redirect / injection via the target input — the input is a free-form string sent as a query param to a same-origin endpoint that validates `max_length=256`. **Control:** client-side length cap matching server cap; no rendering of the target inside HTML attributes that allow script execution.
- **Secrets/key handling:** None. The chore introduces no new secrets, no LLM calls, no third-party requests.
- **Auditability:** N/A — read-only view; `audit_log` is MVP3.
- **Data retention/deletion/export impact:** None.

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement:** `/clusters/[id]` page, mounted in the `ClusterDetailView` JSX between `<ClusterActionBar>` and `<ClusterDetailIndicesCard>`. No new top-level route; no sidebar entry.
- **Labeling taxonomy:** the card title is **"UBI readiness"** (matches the glossary key `cluster.ubi_readiness` and the four `RUNG_LABELS` in the existing badge). The query-set picker label is **"Query set"**, matching `/query-sets` and the studies-create wizard. The target input label is **"Target"** — the existing field on `ClusterDetail` is also labeled "Target filter" in `ClusterDetailSummary`; the readiness card uses the shorter form because the value is the same conceptual thing (an application filter) but the operator is *choosing* it in-context rather than *displaying* a stored value.
- **Content hierarchy:** Card header "UBI readiness" with `<HelpPopover glossaryKey="cluster.ubi_readiness">` (already keyed); card body: pickers row (query-set + target side-by-side on `md:` and stacked on mobile) → divider → result row (badge + chip + caption when applicable). Empty state replaces the entire body.
- **Progressive disclosure:** The card is always visible; its body conditionally renders. No hidden / collapsed sections.
- **Relationship to existing pages:** the card sits adjacent to existing cluster-detail composition; no existing card is replaced. `ClusterDetailSummary` loses the chip but keeps every other capability (name, engine, environment, auth, base URL, target_filter row, version, notes).

### Tooltips and contextual help

| Element | Tooltip / help text | Trigger | Placement | Source |
|---|---|---|---|---|
| Card header "UBI readiness" | Re-uses the existing `cluster.ubi_readiness` glossary entry (long-form description of the four rungs) | hover / focus on `<HelpPopover>` info icon | top | Existing glossary key (no new entry). |
| Empty-state hint | "Create a query set to check UBI readiness for this cluster." — inline copy, plus a Link | inline | inline | New copy (no glossary entry needed — instruction text, not domain term). |
| Fallback caption (unified for 404 + 503) | "Couldn't refresh UBI status (cluster unreachable or query set missing)." | inline | inline (next to badge) | New copy (no glossary entry — operator-facing error text). D-10: identical for 404 and 503 because the hook doesn't expose which fired. |
| Synthetic-data chip | Existing tooltip from `<DemoBadge variant="synthetic-ubi">` (unchanged) | hover / focus | top | Existing chip (no new copy). |

### Primary flows

1. **Demo cluster (auto-seeded resolved state).** Operator visits `/clusters/acme-products-prod` → card mounts; `useQuerySets` returns 1 query set; `cluster.target_filter` is non-null → both controls auto-seed → `useUbiReadiness` returns `rung_3` from the 60 s cache → badge renders adjacent to the synthetic-data chip → `ClusterDetailSummary` no longer shows the chip.
2. **Multi-query-set production cluster.** Operator visits `/clusters/prod-search-en` → 5 query sets, `target_filter` populated → no auto-seed (more than one query set) → operator picks "main-product-queries" + the placeholder-seeded target → 200 ms debounce → badge renders (e.g., `rung_2`).
3. **Operator overrides the target.** Auto-seeded state shows `rung_1` with the cluster's `target_filter` → operator types a different index name (`legacy-products-v3`) → 200 ms debounce → badge re-renders with the new rung for that target.

### Edge/error flows

- **Empty cluster (no query sets).** Card shows the hint with a Link to the create flow. No badge, no chip (the chip lives with the badge — no badge means no chip; this is a behavior change vs. today where demo clusters show the chip even without a query set, but the only synthetic-UBI demo clusters already have query sets seeded so the observable change is nil).
- **`useQuerySets` errored.** Inline error "Couldn't load query sets" with a retry. No badge, no chip.
- **Cluster unreachable OR query set missing.** Hook returns `rung_0` synthetic fallback → badge reads `rung_0` + unified caption "Couldn't refresh UBI status (cluster unreachable or query set missing)." (D-10 — frontend cannot distinguish the two.)
- **422 mismatch (defensive).** Hook re-throws (not 404 / 503); card surfaces "Couldn't load UBI readiness" with retry. Should not be reachable through the picker since the picker is `cluster_id`-scoped.

## 12) Given/When/Then acceptance criteria

### AC-1: Card mounts inside cluster-detail page

- Given a non-deleted cluster id `c1`
- When the operator navigates to `/clusters/c1`
- Then the `<ClusterDetailUbiReadinessCard>` is in the DOM (queryable via the card title "UBI readiness"), positioned in the document order between `<ClusterActionBar>` and `<ClusterDetailIndicesCard>`.

### AC-2: Auto-seed on demo cluster (Playwright fixture: `acme-products-prod`)

- Given the seeded demo cluster `acme-products-prod` (anchored to [`backend/app/services/demo_ubi_seed.py:74`](../../../../backend/app/services/demo_ubi_seed.py) which seeds `(slug="acme-products-prod", target="products")`, and to [`backend/tests/unit/scripts/test_scenarios_ubi_config.py:99`](../../../../backend/tests/unit/scripts/test_scenarios_ubi_config.py) which fixes the expected rung to `rung_3` for this slug under the seeded `ctr_threshold` converter) with exactly one query set and `target_filter = "products"`
- When the page mounts after `make seed-demo` has run
- Then on first React Query settled state, the query-set `<select>` reads the seeded query set's id, the target input value reads `"products"`, and the badge renders with `data-rung` ∈ `{rung_1, rung_2, rung_3}` (non-`rung_0`). The Playwright spec asserts non-`rung_0` rather than hardcoding `rung_3` so future seed-converter changes don't cascade-break this spec.
- Example values:
  - Cluster slug: `acme-products-prod`
  - Expected `data-rung` (assert with `expect(...).not.toBe('rung_0')`): one of `rung_1` / `rung_2` / `rung_3` (currently `rung_3` per the cited test config)
  - Expected chip: exactly one `data-testid="demo-badge-synthetic-ubi"` adjacent to the badge.

### AC-3: No auto-seed when multiple query sets exist OR pagination has more rows

- Given a cluster `c-multi` whose `useQuerySets({ cluster_id, limit: 2 })` returns either (a) 2 rows on the first page, or (b) 1 row with `has_more === true`, OR a cluster with one query set but `target_filter` null/empty
- When the page mounts
- Then the query-set `<select>` is unselected (value === ""), the target input is empty, and the badge is not rendered.
- And: typing a target without picking a query set does NOT issue the readiness call (assertion: `useUbiReadiness` returns null while either param is empty).

### AC-4: Empty-state hint when no query sets

- Given a freshly-registered cluster `c-empty` with zero query sets
- When the page mounts
- Then the card body renders the text "Create a query set to check UBI readiness for this cluster." and a Link element pointing at the query-set create flow.
- And: no `<UbiRungBadge>` is in the DOM. No `<DemoBadge>` is in the DOM.

### AC-5: Synthetic-data chip relocates

- Given any demo synthetic-UBI cluster (e.g., `acme-products-prod`, `corp-docs-search`, or `jobs-marketplace-prod`) per `isDemoSyntheticUbiClusterName`
- When the page mounts
- Then exactly **one** `<DemoBadge variant="synthetic-ubi">` is in the DOM (assert `getAllByTestId('demo-badge-synthetic-ubi').length === 1`).
- And: it is **inside** the `<ClusterDetailUbiReadinessCard>` (containment assertion — the chip's nearest card ancestor's title reads "UBI readiness").
- And: it is **not** inside `<ClusterDetailSummary>` (assert no descendant of the summary card has `data-testid="demo-badge-synthetic-ubi"`).

### AC-6: No chip on non-demo cluster

- Given a non-demo cluster `c-prod` (where `isDemoSyntheticUbiClusterName(cluster.name)` is false)
- When the page mounts and the card resolves to any rung
- Then no `<DemoBadge variant="synthetic-ubi">` is rendered anywhere on the page.

### AC-7: 404/503 graceful degradation surfaces unified caption

- Given a cluster whose readiness endpoint returns either 503 `CLUSTER_UNREACHABLE` OR 404 `QUERY_SET_NOT_FOUND`
- When the readiness hook degrades to its synthetic `rung_0` fallback (signaled by `covered_pairs_pct === null && head_covered === null`)
- Then the card renders `<UbiRungBadge rung="rung_0" />` AND a single muted caption "Couldn't refresh UBI status (cluster unreachable or query set missing)" adjacent to the badge — the caption text is **identical** for both 404 and 503 because the hook does not expose which (D-10).
- And: no toast / error banner appears elsewhere on the page.

### AC-8: Picker edits re-fire the readiness call (debounced); previous badge stays visible

- Given an auto-seeded resolved state showing `rung_1` for `(qs-A, target-X)`
- When the operator types `target-Y` into the target input
- Then within 250 ms (200 ms debounce + headroom) the readiness hook re-fetches with `target=target-Y`.
- And: the previous badge value (`rung_1`) **MUST** remain visible while the new request is in flight (no skeleton flash on edit). The mechanism is a one-line patch inside `ui/src/lib/api/ubi.ts`: add `placeholderData: keepPreviousData` (imported from `@tanstack/react-query`) to the `useUbiReadiness` `useQuery` options. The card calls the hook with no wrapper. Vitest assertion: after editing the target, the badge's text node is continuously present (no intermediate skeleton render) until the new response resolves and the text updates.

### AC-8b: Clearing a control after resolve does NOT leak a stale badge

- Given an auto-seeded resolved state showing `rung_1` for `(qs-A, target-X)`
- When the operator clears EITHER the target input (to `""`) OR the query-set picker (via the small "Clear" button next to the `<Select>` — required because Radix `<Select>` does not support an empty-value `<SelectItem>`; impl plan §UI Guidance documents the affordance)
- Then `useUbiReadiness` does **not** issue a new request (its `enabled` predicate is false once any param is empty).
- And: the card **does not render** the badge or the synthetic-data chip — the FR-5 dual-gate (response non-null AND current picker state valid) returns false on the "current picker state valid" half (D-16).
- And: typing a non-empty target back in OR re-selecting a query set re-resolves the badge from cache (or, if the cache window has expired, re-fetches).

### AC-9: Wire enum discipline (no inline rung literals)

- Given the chore is being implemented
- When source files in `ui/src/components/clusters/cluster-detail-ubi-readiness-card.tsx` (or wherever the card lives) are inspected
- Then the file contains **zero** inline rung-string literals (regex `/['"\`]rung_[0-3]['"\`]/` matches zero times). The card flows `readinessQuery.data.rung` directly into `<UbiRungBadge rung={…} />` without re-typing the rung value as a string literal; the `UbiReadinessRung` type comes through the `UseQueryResult` generic from `useUbiReadiness` without needing an explicit import in the card.
- And: the file does not introduce any new `<SelectItem>` whose `value` is an inline literal from an enum already in `@/lib/enums.ts` (CLAUDE.md form-select-discipline rule). The picker `<SelectItem>` values are DB row ids (dynamic), not enum literals.
- Note: this AC was relaxed in GPT-5.5 plan-review cycle 1 (finding B7) from the prior import-existence assertion — the substantive guardrail is "no inline literals," not "must import the enum name."

### AC-10: No backend regressions

- Given no backend / migration / schema changes are introduced
- When `make test-unit && make test-integration && make test-contract` run
- Then all suites pass with no new tests added under `backend/` and no existing tests modified — the readiness endpoint contract is unchanged.

## 13) Non-functional requirements

- **Performance:** First paint of the card matches the cluster-detail render (no new blocking load — `useQuerySets` is React Query default `pending`-skeleton). Readiness request resolved within the existing 60 s cache TTL on the second open; first open is a single GET. Debounce on target edits: 200 ms.
- **Reliability:** No new code paths that can crash the cluster-detail page. The card is fully isolated — if `useQuerySets` errors, the rest of the cluster-detail page renders unchanged.
- **Operability:** No new metrics / logs / alerts. The endpoint already emits its existing structured logs (`feat_ubi_judgments`).
- **Accessibility:** the query-set `<select>` uses a labeled `<Label htmlFor>` pair; the target `<input>` likewise. The badge already exposes `data-rung` and visible text; the synthetic-data chip likewise. Card region is wrapped in a `<section aria-labelledby>` keyed to the card title for screen-reader announcement.

## 14) Test strategy requirements

- **Unit tests:** N/A — pure-frontend chore; the only deterministic logic is the auto-seed predicate `(query_sets.length === 1 && cluster.target_filter)`. Tested by the vitest spec below as part of the component test, not as a separate unit test file.
- **Integration tests:** N/A — no backend changes.
- **Contract tests:** N/A — no new endpoints / response shapes.
- **Vitest component test** (`ui/src/__tests__/components/clusters/cluster-detail-ubi-readiness-card.test.tsx`): covers all four interior states (empty / pickers-unset / auto-seeded / resolved), the 503 caption, the inline error, the chip placement (present adjacent to badge on demo clusters, absent on non-demo, length ≤ 1 globally), wire-enum-discipline (FR-8 source-file inspection).
- **Vitest regression test** for `cluster-detail-summary.test.tsx` (existing or new): asserts that `<DemoBadge variant="synthetic-ubi">` is **not** present inside the summary card on demo clusters (relocation, not duplication).
- **Playwright E2E** (`ui/tests/e2e/cluster-detail-ubi-readiness.spec.ts`): visit a seeded `acme-products-prod` demo cluster against a live backend → assert badge `data-rung` is non-`rung_0` → assert one synthetic-UBI chip in the readiness card → assert zero chips next to the cluster name. **MUST NOT** use `page.route()` mocking (CLAUDE.md E2E rules).

## 15) Documentation update requirements

- `docs/01_architecture/ui-architecture.md`: add a one-paragraph note under cluster-detail composition mentioning `<ClusterDetailUbiReadinessCard>` and its placement between the action bar and the indices card. (Optional — only update if the existing doc already enumerates the cluster-detail children.)
- `docs/02_product/`: no update — no user-flow change beyond the badge appearing on cluster-detail.
- `docs/03_runbooks/`: no update — operator behavior is "look at /clusters/[id]"; no new procedure.
- `docs/04_security/`: no update — no new threat surface.
- `docs/05_quality/`: no update — coverage gates unchanged.

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** None. Frontend-only chore behind a single PR; rollout is the merge.
- **Migration/backfill expectations:** None — no schema changes.
- **Operational readiness gates:** the standard CI gates (vitest, ESLint, tsc, Next build, Playwright smoke) must pass on the PR. No additional gates.
- **Release gate:** the Phase-1 `feat_demo_ubi_study_comparison` E2E (if it references the synthetic-UBI chip placement) MUST pass with the relocated selector. The implementation plan re-anchors the selector in the same PR.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks (impl plan) | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 (card mount) | AC-1 | Story 1 (component scaffold + mount in `ClusterDetailView`) | vitest component test; Playwright | `ui-architecture.md` (optional) |
| FR-2 (query-set picker) | AC-3, AC-4 | Story 2 (cluster-scoped picker + empty state) | vitest component test | — |
| FR-3 (target input) | AC-8 | Story 3 (target input + debounce + length cap) | vitest component test | — |
| FR-4 (auto-seed) | AC-2, AC-3 | Story 4 (auto-seed predicate) | vitest component test | — |
| FR-5 (resolved + chip relocation + leak guard) | AC-2, AC-5, AC-6, AC-8b | Story 5 (badge render + chip relocation + summary diff + dual-gate leak guard per D-16) | vitest component test; vitest summary regression test; Playwright | — |
| FR-6 (empty state) | AC-4 | Story 2 | vitest component test | — |
| FR-7 (loading / error UX) | AC-7 | Story 6 (unified fallback caption + inline error + retry) | vitest component test | — |
| FR-8 (test coverage) | AC-9, AC-10 | Story 7 (vitest suite + Playwright spec + run gates) | as above | — |
| Shared-hook patch (D-15) | AC-8, AC-8b | Story 8 (one-line `placeholderData: keepPreviousData` in `ui/src/lib/api/ubi.ts`) | vitest assert via the card spec; existing dialog tests unaffected | — |

## 18) Definition of feature done

This feature is complete when:

- [ ] AC-1 through AC-10 pass in CI.
- [ ] Vitest spec at `ui/src/__tests__/components/clusters/cluster-detail-ubi-readiness-card.test.tsx` covers all four interior states + chip placement.
- [ ] Vitest regression on `cluster-detail-summary.test.tsx` asserts the chip is absent from the summary card.
- [ ] Playwright E2E for the auto-seeded demo cluster passes against the live backend.
- [ ] No backend / migration / schema files are touched (CI assertion: the PR diff under `backend/` is zero lines). The shared-hook touch is `ui/src/lib/api/ubi.ts` only (one line — D-15).
- [ ] `ui-architecture.md` cluster-detail composition note added (if that doc enumerates children today).
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

_None._ All three open questions from idea.md were resolved into D-1 through D-7 below.

### Decision log

- 2026-06-01 — **D-1 (idea Q-1, "surface vs leave off"): SURFACE THE BADGE.** Rationale: the alternative ("leave it off, re-word Phase 1") is strictly a documentation patch and would leave the operator unable to see UBI readiness on cluster-detail at all — the gap this chore exists to close. The relocation of the synthetic-data chip to its originally-specified position is a corroborating benefit. The "leave it off" branch is preserved here as the explicit non-goal in §3.
- 2026-06-01 — **D-2 (placement on cluster-detail): BETWEEN `<ClusterActionBar>` AND `<ClusterDetailIndicesCard>`.** Rationale: above the indices card mirrors the operator's read-order — "what is this cluster + what can I do with it + what's its UBI readiness + what indices does it have + what studies use it." Putting the readiness card immediately after the action bar keeps UBI-readiness conceptually adjacent to the actions an operator might take next (generate judgments / start a study).
- 2026-06-01 — **D-3 (backend changes): NONE.** Rationale: every dependency already exists (endpoint, hook, badge, query-sets filter). A backend "default query set + target hint" endpoint was considered and rejected — the frontend computes the auto-seed locally and there is no second caller.
- 2026-06-01 — **D-4 (on-ramp nudge on cluster-detail): NO.** Rationale: `<UbiOnrampNudge>` belongs to `feat_ubi_judgments` FR-8 and currently lives in the generate-judgments dialog. Mounting it on cluster-detail would re-open the on-ramp surface design that the dialog already addresses. The `rung_0` state on cluster-detail surfaces the rung label with the caption "Cluster unreachable…" (if 503) or no caption (if truly rung_0 from data); the nudge stays in the dialog.
- 2026-06-01 — **D-5 (target picker enumerating indices via adapter): NO.** Rationale: free-form text input with `cluster.target_filter` as the seed is sufficient for MVP2. A real index picker would call `list_targets` on every page load and re-open adapter-call cost / latency design.
- 2026-06-01 — **D-6 (refactor badge to context-aware shape): NO.** Rationale: cycle-3 of `feat_ubi_judgments` removed exactly that pattern (`readiness-snapshot-badge-contract-drift`). The badge stays a pure rung-renderer; the new card holds the data-fetching logic.
- 2026-06-01 — **D-7 (deep-link picker state in URL): NO.** Rationale: read-only card with no need for shareable state. Adding `?query_set_id=…&target=…` would introduce a URL contract for a feature that has no return-visit semantics.
- 2026-06-01 — **D-8 (auto-seed heuristic, idea Q-2): ONE-QUERY-SET-ONLY.** Rationale: the operator-friendly variant ("most-recent of multiple") risks silently picking the wrong context on multi-query-set clusters. Restricting auto-seed to "exactly one query set AND a non-null `target_filter`" makes the demo clusters zero-click without ever surprising a production user. Multi-query-set clusters show empty pickers.
- 2026-06-01 — **D-9 (empty state when no query sets, idea Q-3): TEXT HINT WITH LINK, NOT `rung_0` BADGE.** Rationale: `rung_0` should mean "checked, no UBI data," not "never checked." A freshly-registered cluster with no query sets has not been checked — rendering `rung_0` would conflate "no query sets exist" with "the cluster has no UBI traffic."
- 2026-06-01 — **D-10 (GPT-5.5 cycle-1 finding #1 — caption disambiguation for 404 vs 503 fallback): UNIFIED CAPTION, NO HOOK CHANGE.** Rationale: the existing `useUbiReadiness` hook returns the same `{rung_0, covered_pairs_pct:null, head_covered:null}` shape for both 404 and 503 ([`ui/src/lib/api/ubi.ts:89-101`](../../../../ui/src/lib/api/ubi.ts)). Disambiguating would require expanding the hook's return contract (e.g., a new `fallbackReason` field), which touches every existing consumer (the generate-judgments dialog) and broadens the chore beyond "cluster-detail wiring." A single generic caption — "Couldn't refresh UBI status (cluster unreachable or query set missing)" — covers both modes without contract changes. The original FR-5 / FR-7 / AC-7 wording was patched to match.
- 2026-06-01 — **D-11 (GPT-5.5 cycle-1 finding #2 — authoritative single-row test for auto-seed): `data.data.length === 1 && data.has_more === false` WITH `limit: 2`.** Rationale: `useQuerySets({ cluster_id })` is cursor-paginated, so a bare `data.length === 1` check could quietly auto-seed a cluster that has more rows on later pages. The card calls `useQuerySets({ cluster_id, limit: 2 })` so a single page can hold at most 2 rows; auto-seed proves single-cardinality via `length === 1 && !has_more`. We picked `has_more` over `totalCount` because `has_more` is an in-page property of the response body (intrinsic) whereas `totalCount` is read from the `X-Total-Count` header (extrinsic and easier to miss in tests).
- 2026-06-01 — **D-12 (GPT-5.5 cycle-1 finding #3 — Playwright fixture anchor): ASSERT NON-`rung_0`, NOT HARDCODED `rung_3`.** Rationale: the seed *currently* fixes `acme-products-prod` to `rung_3` ([`backend/tests/unit/scripts/test_scenarios_ubi_config.py:99`](../../../../backend/tests/unit/scripts/test_scenarios_ubi_config.py)), but a future seed-converter tweak could shift it to `rung_2` without breaking the chore's contract. The Playwright assertion uses `expect(rung).not.toBe('rung_0')` so the spec stays robust to seed evolution while still proving the auto-seeded resolved state lights up.
- 2026-06-01 — **D-13 (GPT-5.5 cycle-1 finding #4 — AC-8 placeholder data): REQUIRE `placeholderData: keepPreviousData`.** Rationale: the original AC was internally inconsistent (required previous-data behavior but allowed skeleton-on-edit). The crisper requirement makes the test deterministic — the badge text never disappears between the old value and the new value during a target-input edit.
- 2026-06-01 — **D-14 (GPT-5.5 cycle-2 finding #1 — picker vs auto-seed call separation): TWO SEPARATE `useQuerySets` CALLS, PICKER `limit=50` + AUTO-SEED `limit=2`.** Rationale: cycle 1 collapsed both responsibilities into a single `limit: 2` call, which would have silently truncated the picker on multi-query-set clusters (only the first 2 of N would be selectable). The picker uses `limit: 50` (project default page size) plus a `has_more`-gated footer hint pointing the operator at the existing `?q=` name-substring search (sub-decision **D-14b** — server-side filter beats client-side cursor pagination inside a small picker). The auto-seed proof keeps `limit: 2`. React Query's query-key isolation makes the two calls independent caches.
- 2026-06-01 — **D-15 (GPT-5.5 cycle-2 finding #2 — `keepPreviousData` location): PATCH THE SHARED HOOK, NOT A CARD-LOCAL WRAPPER.** Rationale: cycle 1's "reused as-is" claim conflicted with AC-8's `placeholderData` requirement. Adding `placeholderData: keepPreviousData` to `useUbiReadiness`'s internal `useQuery` options is a single-line change that satisfies the card's contract without introducing a card-local wrapper, and the existing dialog consumer is functionally unaffected (its query key only changes on re-open — preserving the prior value across re-opens is a harmless improvement). The non-goal section now flags the one-line hook touch explicitly so the impl plan doesn't conflict with the "frontend-only chore" framing.
- 2026-06-01 — **D-16 (GPT-5.5 cycle-3 finding #1 — stale-badge leak after clearing a picker): GATE BADGE RENDER ON BOTH `response !== null` AND CURRENT PICKER VALIDITY.** Rationale: with `placeholderData: keepPreviousData`, `useUbiReadiness`'s `data` keeps holding the prior response after the operator clears either control, so a single-condition `response !== null` gate would render a stale badge against an empty selection. FR-5 now requires the dual gate (`response !== null AND querySetId !== "" AND target.trim() !== ""`), and AC-8b adds an explicit vitest case proving the badge disappears on clear.
- 2026-06-01 — **D-17 (GPT-5.5 cycle-3 finding #2 — row-array vs response-object nesting): NORMALIZE TO `pickerResponse.data.length`.** Rationale: FR-4 already correctly described the auto-seed proof as `data.data.length === 1` (outer `data` = TanStack `query.data` = response body; inner `data` = row array). FR-6 had been written as `useQuerySets({...}).data.length === 0`, which an implementer might literally read as `query.data.length` and mis-implement. FR-6 now binds a local `pickerResponse = pickerQuery.data` and checks `pickerResponse.data.length === 0`, matching FR-4's nesting and matching the actual `QuerySetListResponse` shape ([`backend/app/api/v1/schemas.py:519-524`](../../../../backend/app/api/v1/schemas.py)).
