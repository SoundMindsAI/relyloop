# Refresh Guide 06 screenshots to capture the new ConfidencePanel

**Date:** 2026-05-21
**Status:** Idea — captured during `feat_pr_metric_confidence` Epic 2 guide-impact assessment
**Priority:** P1 — guide-06 screenshots are stale relative to the shipped ConfidencePanel. Small bounded refresh (~15-30 min). Bundle with the next guide-screenshot sweep.
**Origin:** Step 3 (Guide impact assessment) of /impl-execute for `feat_pr_metric_confidence` Epic 2. The new `<ConfidencePanel>` renders on `/studies/[id]` between `<StudyHeader>` and the trials table. Guide 06 (`06_create_and_monitor_study`) captures study-detail screenshots at [`ui/tests/e2e/guides/06_create_and_monitor_study.spec.ts`](../../../../ui/tests/e2e/guides/06_create_and_monitor_study.spec.ts) lines 73 / 78 / 88 / 96 against a study seeded via `seedStudyCompletedWithDigest()` (no per_query_metrics on the seeded trials).
**Depends on:** None — purely a screenshot regeneration.

## Problem

The shipped guide-06 PNGs at [`ui/public/guides/06_create_and_monitor_study/`](../../../../ui/public/guides/06_create_and_monitor_study/) were captured before the ConfidencePanel mounted on the studies-detail page. Operators reading the walkthrough now see a UI element in their browser that doesn't appear in the corresponding guide screenshot. Small visual drift, not a functional gap.

Because guide-06's seed uses `seedStudyCompletedWithDigest()` (no per_query_metrics), the new section that lands in the screenshot will be the **partial-shape** variant: headline metric only (no CI band), one secondary callout (`runner_up_gap`, since the seed has 2 complete trials), and no per-query outcomes block. That partial view is itself a legitimate teaching surface — operators with old studies will see exactly that on their own UIs.

## Proposed capabilities

- Run `/guide-gen 06 --regen` to re-capture the four study-detail screenshots (the cluster + create-modal + studies-list screenshots earlier in the deck are unaffected by the ConfidencePanel mount).
- Optionally extend `seedStudyCompletedWithDigest()` (or add a `WithConfidence` variant) so the regenerated screenshots include a full ConfidencePanel — depends on whether the operator-facing teaching value of the full panel outweighs the simpler partial-shape seed. Worth deciding at regen time, not now.
- Update [`ui/public/guides/06_create_and_monitor_study/script.md`](../../../../ui/public/guides/06_create_and_monitor_study/script.md) to mention the new section if regen lands with the full panel.

## Scope signals

- **Backend:** none (or one optional helper extension if going with the full-panel seed).
- **Frontend:** screenshot files only; the `metadata.json` captions may need a one-line addition if the new section gets its own caption slide.
- **Migration:** none.
- **Config:** none.
- **Audit events:** N/A.
- **Estimated size:** 15-30 minutes once the operator has `make up` running. The `/guide-gen` skill automates the capture + cross-model visual review.

## Why not yet prioritized

Guide-06 is stale in a low-stakes way — the walkthrough still works end-to-end; only the screenshots lag the live UI. Operators following the walkthrough will see the missing section in their own browser and understand it; they won't get blocked. The regen is worth bundling with the next guide-screenshot refresh sweep (likely triggered by a UI primitive change or design-system update) rather than spinning a dedicated PR for it now.

## Relationship to other work

- **Coordinates with:** the `feat_pr_metric_confidence` Epic 2 ConfidencePanel that just shipped. The screenshots can be captured against any deployed instance once the feature merges.
- **Sibling pattern:** prior `chore_form_dropdown_guide_screenshot_refresh` (PR #154) did the same for the form-dropdown primitive rollout — this is the routine cadence for "UI change → guide regen."
