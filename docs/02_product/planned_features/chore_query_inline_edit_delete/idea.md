# Idea — chore_query_inline_edit_delete

**Date:** 2026-05-12
**Origin:** Surfaced during `feat_studies_ui` implementation-plan generation (GPT-5.5 cycle-1 finding #1). Spec FR-7 mentions "list of queries with edit/delete" on `/query-sets/{id}`, but the backend (per `feat_study_lifecycle` Phase 2 / PR #25) exposes only `POST /api/v1/query-sets/{id}/queries` for bulk add — no per-query PATCH or DELETE endpoints exist on the router (`backend/app/api/v1/query_sets.py`).

## Problem

The `feat_studies_ui` plan called for a "view-only queries table" on the query-set detail page (Story 2.2). During implementation we discovered there is **no GET endpoint to list individual queries either** — the backend exposes only `POST /api/v1/query-sets/{id}/queries` (bulk add). Story 2.2 therefore shipped a count + bulk-add UX on the detail page; per-query inspection is unavailable.

This is a **scoping omission**, not a regression: nothing was lost (the endpoints never existed). But the spec language assumes both listing and edit/delete, so the spec/plan diverge from the backend.

## Why deferred

Backend doesn't expose the surface — implementing the UI without endpoints would require either fake-deleting client-side (data integrity hole) or shipping new backend code mid-feature (out of scope for `feat_studies_ui`, which is explicitly UI-only).

## Proposed scope (when this idea graduates to a spec)

1. **Backend listing endpoint** (prerequisite): add `GET /api/v1/query-sets/{id}/queries?cursor&limit` returning per-query rows. Until this lands, the UI cannot render a real queries table — only a count.
2. **Backend mutations:** add `PATCH /api/v1/query-sets/{id}/queries/{query_id}` (update `query_text`, `doc_id`, `metadata`) and `DELETE /api/v1/query-sets/{id}/queries/{query_id}` (soft or hard delete — TBD per data model). Both validate that the parent query-set is not referenced by any active or completed study (FK consistency; deletion of a query that produced trials would orphan their `qrels` rows).
3. **Frontend:** ship a real `queries-table.tsx` reading from the new listing endpoint + add inline edit (`<Popover>` or row-level form) and delete (with `<AlertDialog>` confirm).
4. **Tests:** integration for backend FK guards; component test for the inline UI.

## Dependencies

- `feat_studies_ui` must ship first (Story 2.2 creates the view-only table).
- No new schema columns required (uses existing `queries` table).

## References

- Spec text: `docs/02_product/planned_features/feat_studies_ui/feature_spec.md` §FR-7
- Implementation-plan scope-deferral note: `feat_studies_ui/implementation_plan.md` Story 2.2 outcome paragraph
- Backend router (current state): `backend/app/api/v1/query_sets.py`
