# chore_cluster_detail_show_target_filter

**Type:** chore — UX completeness
**Date:** 2026-05-21
**Status:** Idea — identified by guide-gen visual audit (guide 01 regen)

## Origin

Surfaced during `chore_guide_01_screenshot_refresh_target_filter` regen.
Slide 5 (`05-cluster-detail.png`) shows the cluster detail page with
fields for Engine / Environment / Auth kind / Base URL / Version / Notes
— but **not** `target_filter`. A user who registered the cluster with
`target_filter='products*'` can't see that setting on the detail page
afterwards.

## Problem

`feat_cluster_target_filter` (PR #168) shipped the column in the DB and
the input on the register modal, but the cluster detail page wasn't
updated to display the value. Operators can:
- See it in the register modal (when creating)
- See its effect (the create-study modal's index picker is scoped)
- Read it via `curl /api/v1/clusters/{id}` (the API returns it)

But on the detail page they can't see it at all. That's the natural
place to surface "this is the filter currently applied".

## Proposed work

Add a `Target filter` field to the cluster detail card in
[`ui/src/app/clusters/[id]/page.tsx`](../../../../ui/src/app/clusters/[id]/page.tsx)
next to (or beneath) the existing fields. Render as:
- Filled: monospace `products*` with the same styling as Base URL
- Empty (NULL): muted text `—` or `not set` (mirrors how MVP1 renders
  other optional fields)

Scope: ~5 LOC frontend, no backend change (the API already returns
`target_filter` per `ClusterDetail`). One unit test asserting the field
renders when set + when null.

## Why deferred (not done inline)

Out of scope for the guide-refresh chore. The guide can still teach the
feature via the register-modal screenshot; this chore makes it
discoverable post-registration. Ship via `/impl-execute --ad-hoc` after
the guide PR merges.

## Related

- [`feat_cluster_target_filter`](../../../00_overview/implemented_features/) — PR #168 shipped the column + register input but missed the detail render
- [`chore_guide_01_screenshot_refresh_target_filter/idea.md`](../chore_guide_01_screenshot_refresh_target_filter/idea.md) — the regen that surfaced this
- [`ui/src/app/clusters/[id]/page.tsx`](../../../../ui/src/app/clusters/[id]/page.tsx) — single insertion point
