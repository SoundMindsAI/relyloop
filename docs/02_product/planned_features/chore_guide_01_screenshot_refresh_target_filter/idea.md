# chore_guide_01_screenshot_refresh_target_filter

**Type:** chore — guide screenshot refresh
**Date:** 2026-05-20
**Status:** Idea — captured during `feat_cluster_target_filter` impl

## Origin

`feat_cluster_target_filter` Story F1 adds a new "Target filter (optional)"
input to `RegisterClusterModal` (immediately below the Notes Textarea).
Guide 01 (`01_register_first_cluster`) screenshots the register-cluster
modal at 3 points in
[`ui/tests/e2e/guides/01_register_first_cluster.spec.ts`](../../../../ui/tests/e2e/guides/01_register_first_cluster.spec.ts).
Those screenshots will show the new field after merge but the existing
guide doesn't mention it.

## Problem

The guide is still operationally correct — the new field is optional,
defaults to null, and doesn't change the happy-path flow described in
the guide. But:

1. New screenshots will show the additional field that the captions don't
   reference, mildly confusing readers
2. The guide misses an opportunity to teach the per-cluster scoping
   feature (the entire motivation behind `feat_cluster_target_filter`)

## Why deferred (not done inline)

The feature PR is already at ~2300 LOC across 18 files; adding guide
regeneration (Playwright run + caption edits + metadata.json updates)
would extend scope. The guide stays operational so this is a polish
item, not a regression.

## Proposed work

Run `/guide-gen 01 --regen` to refresh the screenshots, then update the
guide's captions to teach the new Target filter field as an optional
step ("Restrict this cluster's index picker to a glob like `products*`
so the create-study modal only shows matching indices for this cluster").

Scope estimate: ~30 minutes (Playwright run is ~2min, caption edits ~10min,
review ~10min).

## Sibling coordination

Pairs with the (now-merged)
[`chore_guide_06_screenshot_refresh_target_picker`](../../00_overview/implemented_features/2026_05_20_feat_create_study_target_autocomplete/chore_guide_06_screenshot_refresh_target_picker.md)
follow-up from PR #165 — both are MVP1-shipped-but-unrefreshed-guides.
Could ship together as a single `chore_mvp1_guide_screenshot_sweep` later.

## Related

- [`docs/08_guides/README.md`](../../../08_guides/README.md) — guide system
- [`ui/tests/e2e/guides/01_register_first_cluster.spec.ts`](../../../../ui/tests/e2e/guides/01_register_first_cluster.spec.ts)
- [`feature_spec.md` §11](../feat_cluster_target_filter/feature_spec.md) — UI design for the Target filter input
