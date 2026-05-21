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

### Use realistic seed-scenario data (NOT `walkthrough-{6chars}` placeholders)

The current spec at
[`ui/tests/e2e/guides/01_register_first_cluster.spec.ts:25`](../../../../ui/tests/e2e/guides/01_register_first_cluster.spec.ts#L25)
generates a throwaway cluster name like `walkthrough-a3b9c1` and uses
`local-es` for the credentials ref. That works mechanically but the
resulting screenshots look like dev-test artifacts, not a real operator's
first cluster. The screenshot reader's first impression should be **a
relatable production-style scenario**, mirroring what `make seed-demo`
already plants into a fresh dev DB ([`scripts/seed_meaningful_demos.py`](../../../../scripts/seed_meaningful_demos.py)).

When `/guide-gen 01 --regen` runs, update the spec to use the
**acme-products-prod** scenario verbatim from the seed file (the first
e-commerce scenario — most relatable for the first-touch screenshot).
Keep a `randomUUID().slice(0, 6)` suffix on the cluster name so the
test doesn't collide with an already-seeded `acme-products-prod` row;
everything else should match the seed:

| Field | Value | Source |
|---|---|---|
| Name | `acme-products-prod-${uuid6}` | mirrors seed slug + collision suffix |
| Engine type | `elasticsearch` | seed |
| Base URL | `http://elasticsearch:9200` | seed (host-network alias inside the Compose network) |
| Auth kind | `es_basic` | seed |
| Credentials ref | `local-es` | seed |
| Environment | `prod` | seed |
| Notes | `"Production Elasticsearch cluster — e-commerce product search."` | new, infers from seed's "e-commerce" framing |
| **Target filter** | `products*` | seed — the whole point of this guide refresh |

The Step 6 detail-page screenshot then shows a realistic operator landing
page with the target filter glob visible — which is exactly what the
caption update should call out.

**Caption update for the new Target filter step** (between Step 03 and 04 in the existing guide):

> "**Optional: restrict this cluster's index picker.** Many production
> Elasticsearch clusters host indices for multiple products or teams.
> Set Target filter to a glob like `products*` so when you later
> create a study against this cluster, the index picker only shows
> matching indices instead of every index on the box. Brace expansion
> isn't supported (`docs-{en,fr}*` won't work); use multiple registrations
> or a wider glob like `docs-*`."

**Important — keep the test self-contained.** The Playwright spec
shouldn't depend on `make seed-demo` having run; it just borrows the
seed scenario's *naming + field values* to produce believable screenshots.
The spec still creates its own cluster via the modal (with the
collision-suffixed name) so a clean dev stack will render the guide
correctly without any prerequisite seed step.

## Sibling coordination

Pairs with the (now-merged)
[`chore_guide_06_screenshot_refresh_target_picker`](../../00_overview/implemented_features/2026_05_20_feat_create_study_target_autocomplete/chore_guide_06_screenshot_refresh_target_picker.md)
follow-up from PR #165 — both are MVP1-shipped-but-unrefreshed-guides.
Could ship together as a single `chore_mvp1_guide_screenshot_sweep` later.

## Related

- [`docs/08_guides/README.md`](../../../08_guides/README.md) — guide system
- [`ui/tests/e2e/guides/01_register_first_cluster.spec.ts`](../../../../ui/tests/e2e/guides/01_register_first_cluster.spec.ts)
- [`feature_spec.md` §11](../feat_cluster_target_filter/feature_spec.md) — UI design for the Target filter input
