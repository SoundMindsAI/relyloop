# Idea — chore_cluster_delete_ui

**Date:** 2026-05-12
**Status:** Idea — gap surfaced during `feat_studies_ui` first-run testing (2026-05-12 after PR #50 + the CORS fix landed).
**Origin:** Operator first-run testing surfaced 7 stale cluster rows (1 with `credentials_ref='ref'` raising `CREDENTIALS_RESOLUTION_FAILED`, 6 fixtures named `c-*` with `base_url=http://x` returning unreachable). The backend exposes `DELETE /api/v1/clusters/{id}` (per `infra_adapter_elastic` Story 3.2) and it works — the operator had to clean them up via `curl -X DELETE` because the UI shipped without a delete affordance.
**Depends on:** None — backend endpoint already ships.

## Problem

The `/clusters` list page (Story 2.1) and `/clusters/{id}` detail page render registered clusters fine, but there is no Delete button. When an operator registers a cluster with stale credentials or a typo'd `base_url`, the row sits in the list permanently. The only paths out today are:

- `curl -X DELETE http://localhost:8000/api/v1/clusters/{id}` — works, but requires shell access and copying UUIDs from the browser URL.
- `make reset` — destroys the entire stack, not viable for incremental cleanup.

The plan's `cluster-detail-summary` component intentionally omitted the delete button (MVP1 scoping — focus was on the read paths + register modal). The first time an operator misconfigures a cluster they hit this gap.

## Proposed capabilities

### Cluster detail page: Delete button

- A red **Delete cluster** button in the action row of `/clusters/{id}` (next to where future Edit / Run Query actions would land).
- Click opens an `<AlertDialog>` with two warnings:
  - "This will soft-delete the cluster from the registry. Studies, query sets, judgment lists, and proposals scoped to this cluster will remain but will lose their parent reference."
  - "Type the cluster name to confirm" (text-input gate to avoid accidental clicks).
- Confirm fires `DELETE /api/v1/clusters/{id}`; on 204 → toast success + navigate back to `/clusters`.
- On non-204 (e.g., 409 if the backend later adds FK guards) → leave the dialog open and show the `error_code` inline.

### Cluster list page: row-level delete (optional)

- Each row in `clusters-table.tsx` could carry a kebab menu (`⋮`) with **Delete** as the only item. Cheaper than navigating into the detail page to delete an obviously-broken row (`health=unreachable`, no studies attached).
- Same `<AlertDialog>` confirmation as the detail-page variant.
- Operator UX call: pick one of (detail-only) vs. (detail + row-level) per the spec session.

## Scope signals

- **Backend:** none — `DELETE /api/v1/clusters/{id}` already returns 204 + soft-deletes the row per `clusters` repo (`infra_adapter_elastic`). The clusters list endpoint already filters `deleted_at IS NULL`. No new endpoints, no migration.
- **Frontend:**
  - `ui/src/lib/api/clusters.ts`: add `useDeleteCluster()` mutation that invalidates `['clusters']` on success.
  - `ui/src/components/clusters/cluster-detail-summary.tsx` (or a new `cluster-action-bar.tsx` mirroring `study-action-bar.tsx`): add Delete button + AlertDialog with type-name confirm.
  - Optionally `ui/src/components/clusters/clusters-table.tsx`: row-level kebab.
- **Migration:** N/A.
- **Config:** N/A.
- **Audit events:** N/A in MVP1. When MVP2 audit-log lands, this is the canonical `CLUSTER_DELETED` event type per `docs/01_architecture/data-model.md` §Forthcoming.

## Why deferred

The `feat_studies_ui` plan scoped Story 2.1 to read paths + register modal (operator's primary task is bringing clusters into the registry, not removing them). Delete became necessary the first time anyone typo'd a `credentials_ref` or `base_url`. It's a 1-story chore — no backend work, well-bounded UI changes.

## References

- Backend endpoint: `backend/app/api/v1/clusters.py:219` (`@router.delete("/clusters/{cluster_id}")`).
- Pattern to copy: `feat_studies_ui` Story 3.4's `study-action-bar.tsx` (cancel-study confirmation via `<AlertDialog>`) — the cluster delete UX is structurally identical, swap in a destructive button + name-typing confirm gate.
- Operator session that surfaced this (2026-05-12): 7 broken cluster rows hand-deleted via `curl -X DELETE` after registering with stub `credentials_ref` values during early testing.
