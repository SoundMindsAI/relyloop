# Idea — chore_query_inline_edit_delete

**Date:** 2026-05-12
**Origin:** Surfaced during `feat_studies_ui` implementation-plan generation (GPT-5.5 cycle-1 finding #1). Spec FR-7 mentions "list of queries with edit/delete" on `/query-sets/{id}`, but the backend (per `feat_study_lifecycle` Phase 2 / PR #25) exposes only `POST /api/v1/query-sets/{id}/queries` for bulk add — no per-query PATCH or DELETE endpoints exist on the router (`backend/app/api/v1/query_sets.py`).

## Problem

The `feat_studies_ui` plan ships a **view-only** queries table on the query-set detail page (Story 2.2). Operators can bulk-add via CSV/JSON but cannot edit or delete an individual query through the UI. The spec language ("list of queries with edit/delete") suggests this was intended but the backend never received the supporting endpoints.

This is a **scoping omission**, not a regression: nothing was lost (the endpoints never existed). But the spec/plan now diverge, and operators may expect the inline UX.

## Why deferred

Backend doesn't expose the surface — implementing the UI without endpoints would require either fake-deleting client-side (data integrity hole) or shipping new backend code mid-feature (out of scope for `feat_studies_ui`, which is explicitly UI-only).

## Proposed scope (when this idea graduates to a spec)

1. **Backend:** add `PATCH /api/v1/query-sets/{id}/queries/{query_id}` (update `query_text`, `doc_id`, `metadata`) and `DELETE /api/v1/query-sets/{id}/queries/{query_id}` (soft or hard delete — TBD per data model). Both validate that the parent query-set is not referenced by any active or completed study (FK consistency; deletion of a query that produced trials would orphan their `qrels` rows).
2. **Frontend:** add inline edit (`<Popover>` or row-level form) and delete (with `<AlertDialog>` confirm) to `ui/src/components/query-sets/queries-table.tsx`.
3. **Tests:** integration for backend FK guards; component test for the inline UI.

## Dependencies

- `feat_studies_ui` must ship first (Story 2.2 creates the view-only table).
- No new schema columns required (uses existing `queries` table).

## References

- Spec text: `docs/02_product/planned_features/feat_studies_ui/feature_spec.md` §FR-7
- Implementation-plan scope-deferral note: `feat_studies_ui/implementation_plan.md` Story 2.2 outcome paragraph
- Backend router (current state): `backend/app/api/v1/query_sets.py`
