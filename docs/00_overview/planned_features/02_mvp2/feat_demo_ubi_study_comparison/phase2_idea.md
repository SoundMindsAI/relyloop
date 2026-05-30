# feat_demo_ubi_study_comparison Phase 2 — side-by-side UBI-vs-LLM study comparison view

**Date:** 2026-05-29
**Status:** Idea — deferred Phase 2 work from `feature_spec.md` §3 "Phase boundaries"
**Priority:** P2
**Origin:** Deferred Phase 2 capability defined in [`feature_spec.md`](./feature_spec.md) §3 "Phase boundaries" and §3 "Out of scope (deferred to Phase 2)". Phase 1 ships the data (dual lists + dual studies on three demo scenarios); Phase 2 wraps the cross-tab manual comparison in a dedicated single-page view.
**Depends on:** [`feature_spec.md`](./feature_spec.md) Phase 1 merged (synthetic UBI + dual studies in the demo dataset). Independent of any other in-flight MVP2 feature.

## Problem

After Phase 1 ships, a demo operator who wants to compare the UBI-derived
study against the LLM-derived study on the same scenario must open both
study detail pages in two browser tabs and mentally diff:

- The digest narratives (different prose; different called-out queries).
- The best-trial parameter values (different operating points).
- The best-metric scalar (which path "won" on nDCG@10).
- The convergence curves (did UBI converge sooner?).

This works but is awkward, and the central value proposition of the
feature — "see what changes when you ground judgments in real behavior
instead of an LLM's rubric reading" — is buried behind manual cross-tab
labor. Phase 2 wraps this into a single dedicated page.

## Proposed capabilities

### Side-by-side study comparison view

- New route `/studies/compare?a={study_a_id}&b={study_b_id}` (query-param
  driven so the URL is shareable / linkable from the digest pages).
- Layout: two-column responsive grid with a narrow center column for
  per-row diff highlights.
- Panels (top to bottom):
  1. Study header pair — name, status, judgment-list source (with the
     Phase-1 `Synthetic demo data` chip rendered correctly per
     `isDemoSyntheticUbiClusterName` gating).
  2. Digest narrative diff — render both narratives side-by-side; use
     `diff-match-patch` (or similar) to highlight added/removed sentences
     in the center column.
  3. Best-trial parameter table — column per study, row per parameter;
     center column flags identical values vs different values.
  4. Best-metric scalar comparison with delta annotation.
  5. Convergence-curve overlay (Recharts; two `<Line>` series on the
     same plot, alpha-blended so divergence is visible).
- Entry points: a "Compare with UBI list" button on the LLM study
  detail page (visible when a paired UBI study exists for the same
  query set) and vice versa.

### Cross-link from Phase 1 surfaces

- The Phase 1 dashboard studies table gains a "Compare ↔" affinity
  badge for study pairs from the same query set on a synthetic-UBI
  demo cluster.
- The Phase 1 `ValueDeltaCard` on the judgment-list detail page gains
  a "View matched study comparison" button when a paired study exists.

### Tutorial guide subsection

- [`docs/08_guides/tutorial-first-study.md`](../../../../08_guides/tutorial-first-study.md)
  Step 11 grows a "Compare LLM vs UBI on the same dataset" subsection
  with screenshots of the new comparison view.

## Scope signals

- **Backend:** likely a single new endpoint `GET /api/v1/studies/compare?a={id}&b={id}` returning a pre-aggregated comparison payload (saves the frontend from doing two independent GETs and a third digest fetch). Reuses existing study + digest serializers; no new DB tables.
- **Frontend:** new route `/studies/compare`, new `<StudyComparisonPage>` component, new `useStudyComparison` hook in `ui/src/lib/api/studies.ts`, new diff utility module. Recharts adds one new chart variant (overlay).
- **Migration:** none.
- **Config:** none.
- **Audit events:** none (read-only view).

## Why deferred

Phase 1 ships the data and the existing per-judgment-list value-delta
card — enough for an operator who reads the tutorial to do the
comparison manually across two browser tabs. The dedicated comparison
view is **net-new frontend** (route + page + component + data hooks +
diff utility) that requires its own UX decisions (visual diff
algorithm, mobile/responsive layout, which panels are
progressive-disclosure vs always-visible).

Splitting Phase 2 out keeps Phase 1's PR focused on the seed-side
plumbing (Python generator + reseed wiring + 5 disclaimer-chip
surfaces) and avoids mixing a substantial frontend feature into a
PR whose primary value is data infrastructure. Phase 1 reviewers
can adjudicate the seed work without simultaneously evaluating a
new frontend route's information architecture.

## Relationship to other work

- **Phase 1** ships the dual lists + dual studies and the disclaimer
  chips. Phase 2 consumes that data unchanged.
- **`feat_pr_metric_confidence`** (shipped — `study_confidence.py`)
  provides bootstrap CI / runner-up-gap data that the Phase 2
  metric-comparison panel may surface to help operators interpret
  the LLM-vs-UBI delta beyond a single scalar.
- **`feat_digest_executable_followups`** (shipped) — the Phase 2
  digest-diff panel renders both digests' suggested followups; if
  the two studies suggest divergent next steps that's a useful
  comparison signal in its own right.
- Independent of `chore_ubi_reader_search_after_pagination` and
  `chore_ubi_hybrid_template_render`.
