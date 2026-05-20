# Step 1 "Target index / collection" — autocomplete from cluster's available targets

**Date:** 2026-05-20
**Status:** Idea — surfaced during local verification of PR #163 (`feat_create_study_search_space_builder`) on 2026-05-20. Step 4 builder verification required walking through Step 1, where the UX gap surfaced.
**Origin:** Manual testing session — operator selected a cluster, then had to type the target name from memory into the "Target index / collection" field. Typing a non-existent target (`product1`) triggered four 404s in the browser console (`GET /api/v1/clusters/{id}/schema?target=product1` × 4 attempts via TanStack's default `retry: 3`) AND a global error toast via [`ui/src/components/providers/query-provider.tsx:31`](../../../../ui/src/components/providers/query-provider.tsx#L31) `QueryCache.onError` handler (no `meta.suppressErrorCodes` is set on `useClusterSchema` — `digests.ts:20` is the only call site that suppresses). The field has been a free-text `<Input>` since `feat_studies_ui` (PR #50) shipped; this is pre-existing UX debt, not a regression from PR #163.
**Depends on:** None — purely a Step-1 UX enhancement, independent of the Step-4 builder.

> **Vocabulary note:** The unified cross-engine vocab in [`docs/01_architecture/adapters.md`](../../../01_architecture/adapters.md) and the existing Protocol uses **"target"** to name the thing the operator picks (ES "index", OpenSearch "index", Fusion "collection", Solr "core"). The user-visible label stays "Target index / collection" (as it is today, [`create-study-modal.tsx:454`](../../../../ui/src/components/studies/create-study-modal.tsx#L454)) for operator familiarity; method names, hook names, endpoints, and wire fields use "target" / "targets" throughout this idea to stay consistent with the rest of the codebase.

## Problem

The "Target index / collection" field at Step 1 of the create-study modal is a free-text `<Input id="cs-target">` (see [`ui/src/components/studies/create-study-modal.tsx:457`](../../../../ui/src/components/studies/create-study-modal.tsx#L457)) with placeholder text `"products"`. The operator must:

1. Already know the exact name of a target on the cluster they just picked.
2. Type it character-for-character (no autocomplete, no validation).
3. Eat 4 console 404s + a global error toast on every misspelling (the `useClusterSchema` hook fires `GET /api/v1/clusters/{id}/schema?target=...`; TanStack's default `retry: 3` issues 4 attempts; `QueryCache.onError` triggers `toast.error("target 'product1' not found")` because the hook doesn't set `meta.suppressErrorCodes: ['TARGET_NOT_FOUND']`). The "{N} fields discovered" hint also silently doesn't render — so the operator can't tell whether the schema query succeeded or failed without opening DevTools.

Three concrete frictions:

- **Discovery cost.** A new operator landing on `/studies` has no in-product way to discover what targets their cluster contains. They have to bounce out to Kibana / OpenSearch Dashboards / `_cat/indices` to find a valid name.
- **Typo cost.** No client-side hint that the target doesn't exist until the schema query fires and toasts. The toast is the only signal the field is invalid — there's no inline form-validation hint, and the field doesn't block Next.
- **Console noise + toast spam.** 4 404s per misspelled lookup + one toast per failed query. Operators retrying with edits get a toast for every keystroke that doesn't match.

## Proposed capabilities

### Option A — Autocomplete dropdown (preferred, locked)

Expose the **already-implemented** `SearchAdapter.list_targets()` ([`backend/app/adapters/protocol.py:131`](../../../../backend/app/adapters/protocol.py#L131), implemented in [`backend/app/adapters/elastic.py:354-380`](../../../../backend/app/adapters/elastic.py#L354-L380)) via a new `GET /api/v1/clusters/{id}/targets` endpoint. The adapter method already calls `_cat/indices?format=json` on ES/OpenSearch, returns `list[TargetInfo]{ name, doc_count }`, and filters out system indices (names starting with `.`). Replace the free-text `<Input>` with an `<EntitySelect>` (the existing form-side FK picker primitive — see [`docs/01_architecture/ui-architecture.md` §"Form dropdown primitive"](../../../01_architecture/ui-architecture.md)). The dropdown:

- Loads asynchronously via a new `useClusterTargets(clusterId)` TanStack hook returning the `EntitySelectListPage<TargetInfo>` shape (`{ data, next_cursor: null, has_more: false }` — most clusters have <100 targets, no pagination needed).
- `getLabel(t) → "${t.name} (${t.doc_count?.toLocaleString() ?? '?'} docs)"` so the operator gets size context per option without a separate column.
- Supports free-text fallback for clusters where indices-listing is restricted by ACL (Elasticsearch `security` plugin in production deployments — MVP3+ surface, but the toggle is cheap to ship now). Render an "Enter manually" toggle that falls back to the current `<Input>` behavior.
- **Bundled side-fix**: add `meta: { suppressErrorCodes: ['TARGET_NOT_FOUND'] }` to `useClusterSchema` so the fallback-typing path stops toasting on every misspelled keystroke; the inline "{N} fields discovered" hint already discriminates success from failure when it doesn't render. ~3 LOC, prevents the bug Option B was originally designed to solve.

**Pros:** zero discovery cost; matches the EntitySelect pattern users already see in Steps 2/3 (Query set, Judgment list, Template); production-ACL fallback preserves the current behavior; adapter-side work is zero (already implemented).

**Cons:** new REST endpoint (small — direct passthrough to the existing adapter method, ~30 LOC + contract test). No Protocol or adapter changes needed.

### Option B — Inline validation only (lighter, deferred-fallback)

Keep the free-text `<Input>` but augment the existing `useClusterSchema` hook to set an inline `text-amber-700` hint below the field when the schema 404s ("No target named '`product1`' in cluster `<cluster-name>`. Check spelling or pick a different cluster."), AND add `meta.suppressErrorCodes: ['TARGET_NOT_FOUND']` to silence the global toast.

**Pros:** no backend changes; ~50 LOC frontend; surfaces the typo immediately.

**Cons:** still requires the operator to know the target name. Doesn't solve the discovery problem.

### Recommended default (locked)

**Option A.** The autocomplete is the right UX for a relevance engineer who's about to spend hours tuning queries — they shouldn't have to leave the tool to find the target name. Option A bundles the small `meta.suppressErrorCodes` fix from Option B so the fallback-typing path also stops being noisy.

## Locked decisions

1. **Method/endpoint/hook vocabulary uses "targets" not "indexes".** Matches the Protocol (`list_targets`), the existing `?target=...` query param on `/schema`, the `studies.target` column, and the umbrella spec's unified cross-engine vocab. User-visible label stays "Target index / collection" for operator familiarity.
2. **No new Protocol method or adapter implementation.** The work is purely API-layer (expose the existing `list_targets()`) + frontend. Saves ~80 LOC of backend work the original idea estimated.
3. **Drop per-target health visualization** (the "green/yellow/red status per index" the first draft mentioned). `TargetInfo` only carries `name + doc_count`; adding `health` would require extending the Pydantic model + the adapter's `_cat/indices` `h=` query param + tests across `test_protocol.py` + `test_elastic_schema.py` + `stub_adapter.py`. Out of scope for an MVP1 polish; ES per-index health in single-node dev clusters is famously noisy (yellow on every index because primary OK but replica unassigned). Operators don't need this to pick a target. Defer as a follow-up if real users ask.
4. **List response shape is unpaginated** (`{ data: TargetInfo[], next_cursor: null, has_more: false }`). Compose-deployed clusters in MVP1 have <100 targets; pagination adds zero value. Conforms to `EntitySelectListPage<T>` so the primitive works as-is. `/spec-gen` should confirm this against [`api-conventions.md` §"Pagination"](../../../01_architecture/api-conventions.md) — if the convention is "every list endpoint paginates," the response can still degenerate to a single page with `next_cursor: null`.
5. **Bundle the `meta.suppressErrorCodes: ['TARGET_NOT_FOUND']` fix on `useClusterSchema` into Option A.** Even with the dropdown live, the "Enter manually" fallback still hits the toast bug; fixing both surfaces in one PR avoids leaving the bug live behind a less-trafficked code path.

## Scope signals

### Option A (locked)

- **Backend:** ~30–40 LOC. New `GET /api/v1/clusters/{id}/targets` router endpoint in [`backend/app/api/v1/clusters.py`](../../../../backend/app/api/v1/clusters.py) (model after `get_cluster_schema` at L295-L315 — same `cluster` fetch + `acquire_adapter` pattern, no new error code beyond `CLUSTER_NOT_FOUND` + `CLUSTER_UNREACHABLE`); new `TargetListResponse` schema in [`backend/app/api/v1/schemas.py`](../../../../backend/app/api/v1/schemas.py); 1 contract test; 1 integration test using the existing [`backend/tests/integration/fixtures/stub_adapter.py:57`](../../../../backend/tests/integration/fixtures/stub_adapter.py#L57) `list_targets` stub. No Protocol change. No adapter change.
- **Frontend:** ~150 LOC. New `useClusterTargets` hook in `ui/src/lib/api/clusters.ts`; new `TargetSummary` re-export of `components['schemas']['TargetInfo']`; replace `<Input id="cs-target">` with `<EntitySelect>` consuming the hook; "Enter manually" toggle + conditional render back to `<Input>` for fallback; add `meta.suppressErrorCodes: ['TARGET_NOT_FOUND']` to `useClusterSchema` (3 LOC); updated test in `create-study-modal.test.tsx` (component-level — exercises both modes); 1 e2e case in `studies-create.spec.ts` (pick from dropdown happy path + fallback toggle).
- **Migration:** none.
- **Config:** none.
- **Audit events:** N/A (MVP1, no `audit_log` yet; pure read-path endpoint).

### Option B (deferred fallback)

- **Backend:** N/A.
- **Frontend:** ~50 LOC. Augment `useClusterSchema` to handle 404 gracefully + render an amber inline hint when 404. One vitest assertion + one e2e case.

## Why not implemented inline today

This UX gap is **pre-existing** — has shipped since `feat_studies_ui` (PR #50, 2026-05-12). It's not a regression introduced by PR #163, and was outside the scope of the search-space builder spec. Inline-fix-vs-defer rubric check: Option A is ~180 LOC across backend + frontend + e2e, needs a new REST endpoint + new contract test, and crosses subsystems. That puts it in "Idea file" territory per the CLAUDE.md "Pre-defer diagnostic" table. The bundled side-fix (`meta.suppressErrorCodes` on `useClusterSchema`) is <10 LOC and could be inlined into any adjacent PR if a maintainer wants to land it before this idea reaches `/pipeline`; it stays in-scope here so the cleanup is unified.

## Open questions for /spec-gen

1. **Response pagination shape.** Confirm against [`api-conventions.md` §"Pagination"](../../../01_architecture/api-conventions.md): does the convention require cursor pagination on every list endpoint even when the result is bounded (~tens of targets)? **Recommended default:** unpaginated `{ data, next_cursor: null, has_more: false }` so `<EntitySelect>` consumes it directly.
2. **Sort order.** Alphabetical by `name`, by `doc_count` descending (biggest first), or preserve `_cat/indices` order (engine-defined)? **Recommended default:** alphabetical by `name`. Most operators search by name, not size; `doc_count` shown in the label gives the size hint without affecting ordering.
3. **"Enter manually" toggle persistence.** Sticky-per-cluster in `localStorage`, sticky-per-session, or always reset to "dropdown mode" on modal open? **Recommended default:** always reset (modal is short-lived; ACL-restricted clusters are the exception, not the rule).

## Relationship to other work

- **Independent of** [`feat_create_study_search_space_builder`](../../00_overview/implemented_features/2026_05_20_feat_create_study_search_space_builder/) — different step of the same wizard; touches different code paths.
- **Composes with** [`chore_create_study_wizard_polish`](../../00_overview/implemented_features/2026_05_20_chore_create_study_wizard_polish/) — that chore polished Steps 3/4/5 ergonomics; this idea applies the same level of polish to Step 1.
- **Builds on** [`infra_adapter_elastic`](../../00_overview/implemented_features/2026_05_10_infra_adapter_elastic/) — Option A reuses the existing `SearchAdapter.list_targets()` that infra_adapter_elastic shipped; no Protocol or adapter changes.
- **Coordinate-only with** [`feat_study_clone_from_previous`](../feat_study_clone_from_previous/) — that idea pre-fills the `target` field from a source study at clone time; the field's widget (`<Input>` vs `<EntitySelect>`) is opaque to the pre-fill (`form.setValue('target', sourceStudy.target)` works against both). Either feature can ship first; no ordering dependency.
