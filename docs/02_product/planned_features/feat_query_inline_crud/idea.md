# Idea — feat_query_inline_crud

> **Renamed 2026-05-13 from `chore_query_inline_edit_delete`** during /idea-preflight — the scope (3 new backend endpoints + FK-guard error code + new frontend table component + ~300 LOC) is feature-scale per state.md's `/pipeline`-candidate classification. The `chore_` prefix was misleading.


**Date:** 2026-05-12 (preflighted 2026-05-13)
**Origin:** Surfaced during `feat_studies_ui` implementation-plan generation (GPT-5.5 cycle-1 finding #1). Spec FR-7 mentions "list of queries with edit/delete" on `/query-sets/{id}`, but the backend (per `feat_study_lifecycle` Phase 2 / PR #25) exposes only `POST /api/v1/query-sets/{id}/queries` for bulk add — no per-query PATCH or DELETE endpoints exist on the router ([`backend/app/api/v1/query_sets.py`](../../../../backend/app/api/v1/query_sets.py)). Verified at preflight: the router has 4 endpoints today (`POST /query-sets`, `GET /query-sets`, `GET /query-sets/{id}`, `POST /query-sets/{id}/queries`); none operate on individual queries.

## Problem

The `feat_studies_ui` plan called for a "view-only queries table" on the query-set detail page (Story 2.2). During implementation we discovered there is **no GET endpoint to list individual queries either** — the backend exposes only `POST /api/v1/query-sets/{id}/queries` (bulk add). Story 2.2 therefore shipped a count + bulk-add UX on the detail page; per-query inspection is unavailable.

This is a **scoping omission**, not a regression: nothing was lost (the endpoints never existed). But the spec language assumes both listing and edit/delete, so the spec/plan diverge from the backend.

## Why deferred

Backend doesn't expose the surface — implementing the UI without endpoints would require either fake-deleting client-side (data integrity hole) or shipping new backend code mid-feature (out of scope for `feat_studies_ui`, which is explicitly UI-only).

## Proposed scope (when this idea graduates to a spec)

1. **Backend listing endpoint** (prerequisite): add `GET /api/v1/query-sets/{id}/queries?cursor&limit` returning per-query rows. Cursor pagination + `X-Total-Count` header per [`api-conventions.md`](../../../01_architecture/api-conventions.md). Until this lands, the UI cannot render a real queries table — only the count exposed by the existing `GET /api/v1/query-sets/{id}` endpoint.
2. **Backend mutations:** add
   - `PATCH /api/v1/query-sets/{id}/queries/{query_id}` — update `query_text`, `reference_answer`, and/or `query_metadata` (the actual columns on the `queries` table per [`backend/app/db/models/query.py`](../../../../backend/app/db/models/query.py); note the DB column is named `metadata` but the Python/API field is `query_metadata` because `metadata` is reserved on SQLAlchemy `DeclarativeBase`).
   - `DELETE /api/v1/query-sets/{id}/queries/{query_id}` — hard delete (queries have no `deleted_at` column; introducing one is out of scope here).
3. **FK integrity:** the only FK referencing `queries.id` today is `judgments.query_id` (no `ondelete="CASCADE"` — verified at [`backend/app/db/models/judgment.py:64-67`](../../../../backend/app/db/models/judgment.py#L64-L67)). Deletion of a query that has any judgment row will fail at the DB layer with an FK violation. The DELETE endpoint must return `409 QUERY_HAS_JUDGMENTS` with the affected `judgment_list_id`s listed in the error payload, directing the operator to delete the parent judgment list first. **No CASCADE.** Trials are NOT directly affected — `trials` has no `query_id` FK; per-query data lives in `judgments` only.
4. **Frontend:** ship a real `queries-table.tsx` reading from the new listing endpoint + add inline edit (`<Popover>` or row-level form, consistent with shadcn primitives per `chore_studies_ui_shadcn_polish`) and delete (with `<AlertDialog>` confirm). Surface the `QUERY_HAS_JUDGMENTS` 409 as a toast with a "Delete judgment list first?" link.
5. **Tests:** integration for backend FK guards (delete-with-judgments → 409; delete-without-judgments → 204); component test for the inline UI.

## Locked decisions

The following forks have a clear default and don't need re-litigation at spec time:

1. **PATCH semantics:** the request body PATCHes the named fields (`query_text`, `reference_answer`, `query_metadata`); `query_metadata` is REPLACED whole-object, not deep-merged. Rationale: simpler, matches the convention of the existing `BulkQueriesJsonRequest` payload, and avoids deep-merge edge cases (null vs missing key).
2. **DELETE semantics:** hard delete, guarded by FK check (return 409 if any judgment references the query). No `deleted_at` column added; the FK guard is the integrity backstop. Rationale: data-model precedent (`docs/01_architecture/data-model.md` §"queries" — no soft-delete column), and adding `deleted_at` mid-MVP1 would require parallel changes to every query-listing repo function.
3. **Audit-log integration deferred to MVP2.** This idea proposes new tenant-visible mutations (UPDATE + DELETE on queries). MVP1 has no `audit_log` table (per CLAUDE.md "Activates at MVP2"). When MVP2 lands, these endpoints must emit `QUERY_UPDATED` and `QUERY_DELETED` audit events in the same transaction as the primary mutation. Spec must call this out explicitly.

## Open questions for /spec-gen

These are genuine product/UX calls that need human input at spec time. Recommended defaults included so /spec-gen doesn't start from zero.

1. **Should the GET listing endpoint include a per-query `judgment_count` derived field?** Useful for the UI to show "this query has 12 ratings across 3 judgment lists" before the operator clicks edit. Recommended default: **yes, include** — single denormalized SUBQUERY in the listing, parallels the existing `QuerySetDetail.query_count` pattern.
2. **DELETE error envelope shape for the FK guard:** should the 409 payload include the list of `judgment_list_id`s and their names, or just a count? Recommended default: **include up to N=10 ids+names**, then a `…and {K} more` overflow indicator. Lets the UI render a clickable "Open" list without unbounded payload growth.
3. **Inline edit UX form factor:** `<Popover>` anchored on the row, full-row inline form, or modal? Recommended default: **`<Popover>`** for `query_text` + `reference_answer` (most common edits); modal for `query_metadata` (JSONB; needs the room).

## Relationship to other work

- **`chore_studies_ui_shadcn_polish`** (in `planned_features/`) — sibling that proposes migrating the page-size selector + TopNav to canonical shadcn primitives. When the queries-table component ships, use the shadcn `<Select>` primitive for any per-column sort/filter dropdown.
- **`chore_cluster_run_query_history`** — sibling that adds another "table on the cluster detail page" pattern. Both pages can share a generic `<DataTable>` primitive if one emerges; coordinate at spec time but don't block on it.
- **No coordination needed with** `feat_chat_agent` — the chat agent doesn't currently propose query mutations as agent tools. If that changes, the agent tool surface would call the same PATCH/DELETE endpoints introduced here.

## Dependencies

- `feat_studies_ui` shipped (now at [`docs/00_overview/implemented_features/2026_05_12_feat_studies_ui/`](../../../00_overview/implemented_features/2026_05_12_feat_studies_ui/)).
- No new schema columns required (uses existing `queries` table).

## References

- Spec text: [`docs/00_overview/implemented_features/2026_05_12_feat_studies_ui/feature_spec.md`](../../../00_overview/implemented_features/2026_05_12_feat_studies_ui/feature_spec.md) §FR-7 (lines 158–161 — view-only list of queries; per-query inline edit/delete deferred here) + Decision log entry 2026-05-12 (line 365).
- Implementation-plan scope-deferral note: [`feat_studies_ui/implementation_plan.md`](../../../00_overview/implemented_features/2026_05_12_feat_studies_ui/implementation_plan.md) Story 2.2 outcome paragraph.
- Backend router (current state): [`backend/app/api/v1/query_sets.py`](../../../../backend/app/api/v1/query_sets.py) — 4 endpoints, none per-query.
- Queries model: [`backend/app/db/models/query.py`](../../../../backend/app/db/models/query.py) — columns are `id`, `query_set_id`, `query_text`, `reference_answer`, `query_metadata`.
- Judgments FK (the integrity hazard): [`backend/app/db/models/judgment.py:64-67`](../../../../backend/app/db/models/judgment.py#L64-L67) — `query_id` references `queries.id` without ON DELETE CASCADE.
