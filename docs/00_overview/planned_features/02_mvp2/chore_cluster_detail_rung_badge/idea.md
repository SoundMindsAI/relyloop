# chore_cluster_detail_rung_badge — surface a UBI rung badge on the cluster-detail page

**Date:** 2026-05-31
**Status:** Idea — split out from `feat_ubi_llm_study_comparison` §3 (out-of-scope decision) at spec generation
**Priority:** P2
**Origin:** Two converging pointers:
1. `feat_ubi_llm_study_comparison` spec §3 ("Out of scope") — the cluster-detail rung-badge work was explicitly carved out of the study-comparison feature so that feature's PR stays scoped to the side-by-side comparison view. See [`feat_ubi_llm_study_comparison/feature_spec.md`](../feat_ubi_llm_study_comparison/feature_spec.md) §3.
2. The original Phase-1 placement issue: `feat_demo_ubi_study_comparison` spec FR-7 surface #3 asked for the synthetic-data disclaimer chip "adjacent to the `<UbiRungBadge>`" on the cluster-detail page — but `<UbiRungBadge>` does **not** render on `/clusters/[id]` today. See [`2026_05_30_feat_demo_ubi_study_comparison/feature_spec.md`](../../../implemented_features/2026_05_30_feat_demo_ubi_study_comparison/feature_spec.md) §7 FR-7 #3 (the chip currently sits next to the cluster **name** as a workaround; GPT-5.5's PR #320 review flagged the placement mismatch).

**Depends on:** None hard. Coordinates with `feat_ubi_llm_study_comparison` only in that this chore, once landed, would move the Phase-1 FR-7 #3 chip from "adjacent to the cluster name" to "adjacent to the rung badge" and correct that spec's wording.

## Problem

The `<UbiRungBadge>` component ([`ui/src/components/clusters/ubi-rung-badge.tsx`](../../../../ui/src/components/clusters/ubi-rung-badge.tsx)) renders the UBI-readiness rung (rung_0 → rung_3) for a cluster, but today it is consumed **only** inside the generate-judgments dialog. The cluster-detail page (`/clusters/[id]`) does not show it, because the badge needs `query_set_id` + `target` context that the readiness endpoint requires — and the cluster-detail page has no such context. A cycle-3 plan-review fix in `feat_ubi_judgments` (`readiness-snapshot-badge-contract-drift`) removed the earlier context-free "snapshot" variant of the badge, so there is no longer a way to render a rung badge without a chosen query set + target.

As a result:
- An operator viewing a cluster's detail page can't see at a glance whether that cluster has UBI-ready behavioral data without opening the generate-judgments dialog.
- The Phase-1 `feat_demo_ubi_study_comparison` FR-7 #3 chip placement ("adjacent to the `<UbiRungBadge>`") is unsatisfiable on that surface, so the chip currently sits next to the cluster name instead — a documented workaround, not the intended placement.

## Proposed capabilities

### Decide whether a rung badge belongs on the cluster-detail page at all

This chore's first job is a UX decision, not just an implementation:

- The readiness endpoint requires `(cluster_id, query_set_id, target)`. The cluster-detail page has only `cluster_id`. So surfacing a rung badge here means **introducing a query-set + target selection affordance** on the cluster-detail page (or a default-pick heuristic), OR deciding the badge does not belong here and instead correcting the Phase-1 chip placement wording to "adjacent to the cluster name" permanently.

### If "yes, surface it": query-set / target selection affordance

- A "pick a query set to see UBI readiness" affordance on the cluster-detail page (e.g., a small inline `<select>` of the cluster's query sets + a target picker), or a default-pick heuristic (most-recent query set + its primary target).
- Once a query set + target is selected, call the existing readiness endpoint and render `<UbiRungBadge>` with the result.
- Move the Phase-1 synthetic-data disclaimer chip adjacent to the now-present badge and correct `feat_demo_ubi_study_comparison`'s FR-7 #3 wording.

### If "no, leave it off": correct the Phase-1 wording

- Permanently document that the chip belongs next to the cluster **name** on the cluster-detail page and patch the Phase-1 spec's FR-7 #3 description accordingly.

## Scope signals

- **Backend:** likely none — the readiness endpoint already exists. Possibly a convenience "default query set + target for this cluster" hint if a default-pick heuristic is chosen.
- **Frontend:** cluster-detail page (`ui/src/app/clusters/[id]/page.tsx`) — add a query-set/target selector + conditional `<UbiRungBadge>` render. Plus the chip-relocation edit.
- **Migration:** none expected.
- **Config:** none.
- **Audit events:** N/A — read-only view, MVP2 (audit_log lands at MVP3).

## Why deferred

The rung-badge-on-cluster-detail work needs its own UX decisions (query-set/target picker affordance, default-pick heuristic, where the badge sits in the cluster-detail layout) that don't share design surface with the side-by-side study comparison view. Bundling it into `feat_ubi_llm_study_comparison` would couple that feature's PR to a placement-decision exercise and broaden its scope past "the comparison view." Splitting it out keeps both efforts independently shippable.

## Relationship to other work

- **`feat_ubi_llm_study_comparison`** (the spec that spun this chore out) — independent. The comparison view does not depend on this badge; this chore does not depend on the comparison view.
- **`feat_demo_ubi_study_comparison`** (Phase 1, shipped PR #320) — this chore, if it surfaces the badge, would relocate that feature's FR-7 #3 disclaimer chip and correct its wording.
- **`feat_ubi_judgments`** (shipped) — owns the readiness endpoint and the `<UbiRungBadge>` component this chore would consume.
