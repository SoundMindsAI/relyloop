# Step 1 "Target index / collection" — autocomplete from cluster's actual indexes

**Date:** 2026-05-20
**Status:** Idea — surfaced during local verification of PR #163 (`feat_create_study_search_space_builder`) on 2026-05-20. Step 4 builder verification required walking through Step 1, where the UX gap surfaced.
**Origin:** Manual testing session — operator selected a cluster, then had to type the index name from memory into the "Target index / collection" field. Typing a non-existent index (`product1`) triggered three 404s in the browser console (`GET /api/v1/clusters/{id}/schema?target=product1`) but did not block advancing the wizard. The field has been a free-text `<Input>` since `feat_studies_ui` (PR #50) shipped; this is pre-existing UX debt, not a regression from PR #163.
**Depends on:** None — purely a Step-1 UX enhancement, independent of the Step-4 builder.

## Problem

The "Target index / collection" field at Step 1 of the create-study modal is a free-text `<Input id="cs-target">` (see [`ui/src/components/studies/create-study-modal.tsx:457`](../../../../ui/src/components/studies/create-study-modal.tsx#L457)) with placeholder text `"products"`. The operator must:

1. Already know the exact name of an index/collection in the cluster they just picked.
2. Type it character-for-character (no autocomplete, no validation).
3. Eat a console 404 if they guess wrong (the `useClusterSchema` hook fires `GET /api/v1/clusters/{id}/schema?target=...` and surfaces "{N} fields discovered" as an optional hint — but when the target doesn't exist, the endpoint 404s and the hint silently doesn't render).

Three concrete frictions:

- **Discovery cost.** A new operator landing on `/studies` has no in-product way to discover what indexes their cluster contains. They have to bounce out to Kibana / OpenSearch Dashboards / `_cat/indices` to find a valid name.
- **Typo cost.** No client-side hint that the target doesn't exist until the user clicks Next + reaches Step 5 + tries to submit (and even then, the server-side rejection — if any — surfaces as an opaque error code rather than "no such index").
- **Console noise.** Three 404s log per failed lookup. Not a functional bug (the hook handles the 404 silently), but it pollutes the dev console during exploratory testing and looks like a real error.

## Proposed capabilities

### Option A — Autocomplete dropdown (preferred)

Add a `GET /api/v1/clusters/{id}/indexes` endpoint that lists indexes the cluster can see (Elasticsearch: `GET _cat/indices?format=json`; OpenSearch: same). Replace the free-text `<Input>` with an `<EntitySelect>` (the existing form-side FK picker primitive — see [`docs/01_architecture/ui-architecture.md` §"Form dropdown primitive"](../../../01_architecture/ui-architecture.md)). The dropdown:

- Loads asynchronously via a new `useClusterIndexes(clusterId)` TanStack hook.
- Shows green/yellow/red status per index (e.g., based on health color).
- Supports free-text fallback for clusters where indexes-listing is restricted by ACL (Elasticsearch `security` plugin in production). Render an "I'll type it manually" toggle that falls back to the current `<Input>` behavior.

**Pros:** zero discovery cost; matches the EntitySelect pattern users already see in Steps 2/3; production-ACL fallback preserves the current behavior.

**Cons:** new backend endpoint (small — direct passthrough to ES/OpenSearch `_cat/indices`); needs adapter abstraction (`SearchAdapter.list_indexes()` per `docs/01_architecture/adapters.md`).

### Option B — Inline validation only (lighter)

Keep the free-text `<Input>` but augment the existing `useClusterSchema` hook to set an inline `text-amber-700` hint below the field when the schema 404s ("No index named '`product1`' in cluster `e2e-c-9b7d4eb6`. Check spelling or pick a different cluster."). Silence the console 404 by suppressing the error log on the schema query when status === 404 (the hook can treat 404 as a non-error and just store `{ fields: [] }`).

**Pros:** no backend changes; ~50 LOC frontend; surfaces the typo immediately.

**Cons:** still requires the operator to know the index name. Doesn't solve the discovery problem.

### Recommended default

**Option A.** The autocomplete is the right UX for a relevance engineer who's about to spend hours tuning queries — they shouldn't have to leave the tool to find the index name. Option B is fine as a partial mitigation if Option A lands later.

## Scope signals

### Option A
- **Backend:** ~80–120 LOC. New `SearchAdapter.list_indexes() → list[IndexSummary]` Protocol method + ElasticAdapter implementation; new `GET /api/v1/clusters/{id}/indexes` router endpoint; new contract test asserting the response shape; new integration test against a real ES cluster (or a service-container fixture). No migration.
- **Frontend:** ~150 LOC. New `useClusterIndexes` hook in `ui/src/lib/api/clusters.ts`; replace `<Input id="cs-target">` with `<EntitySelect>` consuming the hook; ACL-fallback toggle; updated test in `create-study-modal.test.tsx`. Likely 1 e2e case.
- **Migration:** none.
- **Config:** none.
- **Audit events:** N/A (MVP1, no audit_log yet).

### Option B
- **Backend:** N/A.
- **Frontend:** ~50 LOC. Augment `useClusterSchema` to handle 404 gracefully (return `{ fields: [] }` without throwing). Add an amber inline hint below the target input when the schema query 404s. One vitest assertion + one e2e case.

## Why not implemented inline today

This UX gap is **pre-existing** — has shipped since `feat_studies_ui` (PR #50, 2026-05-12). It's not a regression introduced by PR #163, and was outside the scope of the search-space builder spec. Capturing as a separate idea so the next sweep can prioritize it against other backlog.

## Relationship to other work

- **Independent of** [`feat_create_study_search_space_builder`](../feat_create_study_search_space_builder/) — different step of the same wizard; touches different code paths.
- **Composes with** [`chore_create_study_wizard_polish`](../../00_overview/implemented_features/2026_05_20_chore_create_study_wizard_polish/) — that chore polished Steps 4/5 ergonomics; this idea applies the same level of polish to Step 1.
- **Builds on** [`infra_adapter_elastic`](../../00_overview/implemented_features/2026_05_10_infra_adapter_elastic/) — Option A's `SearchAdapter.list_indexes()` plugs into the existing adapter Protocol.
