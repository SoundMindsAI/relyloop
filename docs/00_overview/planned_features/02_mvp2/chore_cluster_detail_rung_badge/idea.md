# chore_cluster_detail_rung_badge — surface a UBI rung badge on the cluster-detail page

**Date:** 2026-05-31 (preflight-audited 2026-06-01 — all paths/signatures verified against live codebase; forks framed for spec-gen)
**Status:** Idea — split out from `feat_ubi_llm_study_comparison` §3 (out-of-scope decision); that spec locked the standalone-chore split (its §19 entry 2026-05-31 + FR-7 line)
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

- A "pick a query set to see UBI readiness" affordance on the cluster-detail page. The readiness endpoint (`GET /clusters/{cluster_id}/ubi-readiness`, [`backend/app/api/v1/clusters.py:412-465`](../../../../backend/app/api/v1/clusters.py)) requires **both** `query_set_id` (must belong to this cluster — the endpoint 422s otherwise) and `target` (a free-form application filter / index name, `min_length=1 max_length=256`). There is no per-query-set `target` column to default from, so the affordance needs **two** controls:
  - **Query-set `<select>`:** populate from `useQuerySets({ cluster_id })` ([`ui/src/lib/api/query-sets.ts:52`](../../../../ui/src/lib/api/query-sets.ts)) — already supports the `cluster_id` filter, so the list is naturally scoped to clusters whose query sets exist.
  - **Target input/picker:** free-form, with `cluster.target_filter` as the natural default seed when present (it is the cluster's index/collection scope; nullable).
- Reuse the existing `useUbiReadiness(clusterId, querySetId, target)` hook ([`ui/src/lib/api/ubi.ts:72`](../../../../ui/src/lib/api/ubi.ts)) — it already returns `null` until all three params are set and gracefully degrades to `rung_0` on 404/503, so the badge can mount conditionally without a hard error path.
- Render `<UbiRungBadge rung={readiness.rung} />` once a (query set + target) pair resolves. The badge takes a **single `rung` prop** (confirmed [`ui/src/components/clusters/ubi-rung-badge.tsx:18-20`](../../../../ui/src/components/clusters/ubi-rung-badge.tsx)) — no context-free "snapshot" variant exists.
- Move the Phase-1 synthetic-data disclaimer chip adjacent to the now-present badge and correct `feat_demo_ubi_study_comparison`'s FR-7 #3 wording. The chip currently renders inside `ClusterDetailSummary` next to `cluster.name` ([`ui/src/components/clusters/cluster-detail-summary.tsx:23-30`](../../../../ui/src/components/clusters/cluster-detail-summary.tsx)), gated on `isDemoSyntheticUbiClusterName(cluster.name)`.

### If "no, leave it off": correct the Phase-1 wording

- Permanently document that the chip belongs next to the cluster **name** on the cluster-detail page and patch the Phase-1 spec's FR-7 #3 description accordingly.

## Scope signals

- **Backend:** none. The readiness endpoint (`GET /clusters/{cluster_id}/ubi-readiness`), the `useUbiReadiness` hook, the `<UbiRungBadge>` component, and the `useQuerySets({ cluster_id })` filter all already exist. This is a pure-frontend wiring chore. (A "default query set + target for this cluster" backend hint is **not** needed — `cluster.target_filter` already gives the frontend a target seed, and `useQuerySets({ cluster_id })` already lists the candidate query sets.)
- **Frontend:** cluster-detail page (`ui/src/app/clusters/[id]/page.tsx`) — add a query-set/target selector + conditional `<UbiRungBadge>` render (likely as a new small `ClusterDetailUbiReadinessCard` component to keep the page composition flat, matching the existing `ClusterDetailSummary` / `ClusterDetailIndicesCard` pattern). Plus the chip-relocation edit in `cluster-detail-summary.tsx`.
- **Migration:** none.
- **Config:** none.
- **Enum/option discipline:** the only wire value is the rung enum, already grounded — `UBI_READINESS_RUNG_VALUES` in [`ui/src/lib/enums.ts:158-160`](../../../../ui/src/lib/enums.ts) carries the `// Values must match backend/app/api/v1/schemas.py UbiReadinessRungWire.` source-of-truth comment. No new dropdown of backend-bound literals is introduced (the query-set `<select>` lists DB rows by id, not enum literals; the target input is free-form text, not an allowlisted enum).
- **Audit events:** N/A — read-only view; pre-MVP3 (audit_log lands at MVP3).

## Why deferred

The rung-badge-on-cluster-detail work needs its own UX decisions (query-set/target picker affordance, default-pick heuristic, where the badge sits in the cluster-detail layout) that don't share design surface with the side-by-side study comparison view. Bundling it into `feat_ubi_llm_study_comparison` would couple that feature's PR to a placement-decision exercise and broaden its scope past "the comparison view." Splitting it out keeps both efforts independently shippable.

## Open questions for /spec-gen

- **Q-1 (central UX fork — surface the badge, or leave it off and re-word Phase 1?).** The whole chore turns on this one decision. **Recommended default: yes, surface it** with a minimal query-set `<select>` + free-form target input (seeded from `cluster.target_filter`) on the cluster-detail page, then relocate the synthetic-data chip adjacent to the rendered badge and correct `feat_demo_ubi_study_comparison` FR-7 #3. Rationale: the "no, leave it off" branch is strictly a documentation patch and would leave the operator unable to see a cluster's UBI readiness at a glance from its detail page — the exact gap this chore exists to close. Spec-gen should lock this with a §19 decision-log entry; if the picker UX proves heavier than expected at spec time, the fallback ("no, re-word Phase 1") remains a clean escape.
- **Q-2 (default-pick vs explicit-pick).** Given Q-1 = yes: should the page auto-select the most-recent query set + seed the target from `cluster.target_filter` (zero-click readiness for the common case), or require an explicit pick before any badge renders? **Recommended default: auto-seed when a single obvious candidate exists** (one query set for the cluster AND a non-null `target_filter`), otherwise show the pickers in an unselected state. Keeps the badge visible for the demo clusters (which have both) without guessing wrong on multi-query-set clusters.
- **Q-3 (empty-state when the cluster has no query sets).** A freshly-registered cluster has zero query sets, so no rung can be computed. **Recommended default:** render a short "create a query set to check UBI readiness" hint in place of the picker (link to the query-set create flow), not a `rung_0` badge — `rung_0` should mean "checked, no UBI data," not "never checked."

## Relationship to other work

- **`feat_ubi_llm_study_comparison`** (the spec that spun this chore out) — independent. The comparison view does not depend on this badge; this chore does not depend on the comparison view.
- **`feat_demo_ubi_study_comparison`** (Phase 1, shipped PR #320) — this chore, if it surfaces the badge, would relocate that feature's FR-7 #3 disclaimer chip and correct its wording.
- **`feat_ubi_judgments`** (shipped) — owns the readiness endpoint and the `<UbiRungBadge>` component this chore would consume.
