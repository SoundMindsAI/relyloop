# bug_cluster_detail_studies_unfiltered

**Type:** bug — frontend/backend contract drift
**Date:** 2026-05-21
**Status:** Bug — identified by guide-gen visual audit (guide 01 regen)

## Origin

Surfaced during `chore_guide_01_screenshot_refresh_target_filter` regen.
Slide 5 (`05-cluster-detail.png`) shows the freshly-registered cluster's
"Studies using this cluster" section displaying 4 studies whose
`cluster_id`s belong to **other** clusters (the seeded scenarios from
`scripts/seed_meaningful_demos.py`). The freshly-registered cluster has
zero studies of its own — the table should be empty.

## Root cause (verified)

[`ui/src/components/clusters/studies-by-cluster-table.tsx:29-36`](../../../../ui/src/components/clusters/studies-by-cluster-table.tsx#L29-L36)
sends `cluster_id` to `useStudies({...})`, but
[`backend/app/api/v1/studies.py:284-292`](../../../../backend/app/api/v1/studies.py#L284-L292)
does NOT declare `cluster_id` as a `Query()` parameter on `GET /api/v1/studies`.
FastAPI silently drops the unknown query param → the backend returns the
global studies list → the "Studies using this cluster" section is
effectively unfiltered.

## Problem

- **User confusion:** the heading says "Studies using this cluster" but
  shows studies from every cluster.
- **Information leak (mild):** a low-privilege user on the cluster detail
  page sees studies that shouldn't be visible on this cluster's detail
  page. MVP1 is single-tenant so this is cosmetic, but the contract is
  wrong.

## Proposed fix

Two-line backend change to add the query param + thread it into `repo.list_studies`:

1. `backend/app/api/v1/studies.py` `list_studies()` — add
   `cluster_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None`
   and pass to `repo.list_studies(..., cluster_id=cluster_id)`.
2. `backend/app/db/repo/study.py` `list_studies()` — accept `cluster_id`
   kwarg and apply `WHERE cluster_id = :cluster_id` when set; mirror
   `count_studies` for the X-Total-Count header parity.
3. New contract test asserting `?cluster_id=` filters correctly + a
   2-cluster integration test asserting cross-cluster isolation.

## Scope signals

- **Backend:** ~30 LOC (router param + repo filter + count). 1 contract
  test + 1 integration test.
- **Frontend:** 0 LOC (already sends the param).
- **Migration:** none.
- **Audit events:** none.

## Why deferred (not done inline)

Out of scope for the guide-refresh chore — the regen exposed this but
fixing it is its own backend change with its own tests. Bundle ship via
`/impl-execute --ad-hoc` after the guide PR merges.

## Related

- [`chore_guide_01_screenshot_refresh_target_filter/idea.md`](../chore_guide_01_screenshot_refresh_target_filter/idea.md) — the regen that surfaced this
- [`backend/app/api/v1/studies.py:284`](../../../../backend/app/api/v1/studies.py#L284) — the route missing `cluster_id`
- [`ui/src/components/clusters/studies-by-cluster-table.tsx:29`](../../../../ui/src/components/clusters/studies-by-cluster-table.tsx#L29) — the frontend that already sends it
- Precedent: `bug_judgment_lists_listing_ignores_query_set_filter` (closed in PR #163) was the same shape — frontend sent filter, backend ignored it.
