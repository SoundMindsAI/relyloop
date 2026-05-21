# Refresh guide 06 screenshot for the new target picker

**Date:** 2026-05-20
**Status:** Idea — surfaced during `feat_create_study_target_autocomplete` post-impl guide-impact assessment.
**Origin:** `feat_create_study_target_autocomplete` F2 changes the create-study modal Step 1 visually (target field is now a disabled `<Select>` "Pick a cluster first" placeholder by default, plus a new "Enter manually" toggle button below it, plus the unchanged "{N} fields discovered" hint). The single guide-06 screenshot at [`ui/public/guides/06_create_and_monitor_study/03-create-study-modal.png`](../../../../ui/public/guides/06_create_and_monitor_study/03-create-study-modal.png) — captured by [`ui/tests/e2e/guides/06_create_and_monitor_study.spec.ts:53`](../../../../ui/tests/e2e/guides/06_create_and_monitor_study.spec.ts#L53) — still shows the prior free-text `<Input>` UI.
**Depends on:** `feat_create_study_target_autocomplete` PR must be merged (the screenshot regen runs against the post-merge UI).

## Problem

The walkthrough guide 06 ("Create and monitor a study") shows the operator opening the create-study modal as part of the wizard tour. The single Step-1 screenshot now disagrees with shipped UI — operators following the guide will see something different from what they're shown.

No functional impact (the spec itself only walks the modal opening + closes it immediately; no fill, no submit). The drift is cosmetic but reduces guide trust.

## Why not bundled into the parent PR

- Guide screenshot regen requires `make up` against the post-merge UI + a guide-capture run + PNG diff review. That's a separate operator-environment step.
- Following the established precedent: `chore_form_dropdown_guide_screenshot_refresh` (PR #154, 2026-05-19) regenerated 20 PNGs across 4 walkthroughs in response to `chore_form_dropdown_primitive` (PR #136). Same pattern — UI change ships first, screenshots refresh in a follow-up chore PR.
- The parent feature PR scope is already 6 commits + dashboards + bundled bug fix; adding a binary-diff PNG refresh would muddy the review.

## Proposed capabilities

### Capability 1 — Regenerate guide-06 screenshot

Run `pnpm capture-guides` (or the equivalent guide-specific capture) against the post-merge UI; replace the single PNG at `ui/public/guides/06_create_and_monitor_study/03-create-study-modal.png`; visual-diff against the prior version to confirm only the target field changed.

### Capability 1a — Use realistic seed-scenario data (NOT `e2e-*` placeholders)

The current [`06_create_and_monitor_study.spec.ts`](../../../../ui/tests/e2e/guides/06_create_and_monitor_study.spec.ts) calls `seedFullChain(3)` + `seedStudy(...)`, which produces `e2e-c-{8hex}` / `e2e-qs-{8hex}` / `e2e-jl-{8hex}` / `e2e-tmpl-{...}` / `e2e-study-{8hex}` against target `products`. That works mechanically but the resulting screenshots look like dev-test artifacts on every slide that displays the cluster column, study name, template name, or detail page. Mirroring the **guide 01 precedent** ([PR #177 chore_guide_01_screenshot_refresh_target_filter](https://github.com/SoundMindsAI/relyloop/pull/177)), refresh the spec to use the **acme-products-prod** scenario from [`scripts/seed_meaningful_demos.py`](../../../../scripts/seed_meaningful_demos.py) so the screenshots look like a real production e-commerce tuning workflow — matching what an operator who ran `make seed-demo` would already have in their dev DB. This also gives the user narrative continuity across guides: guide 01 registers `acme-products-prod`, guide 06 creates the first study against it.

Use these values verbatim from `seed_meaningful_demos.py` SCENARIOS[0], with `randomUUID().slice(0, 6)` suffixes on the cluster + study names so reruns and seeded state don't collide:

| Entity | Value | Source |
|---|---|---|
| Cluster name | `acme-products-prod-${uuid6}` | mirrors seed slug + collision suffix |
| Engine | `elasticsearch` | seed |
| Environment | `prod` | seed |
| Base URL | `http://elasticsearch:9200` | seed |
| Auth kind | `es_basic` | seed |
| Credentials ref | `local-es` | seed |
| Target filter | `products*` | seed (now visible on the detail page after PR #177) |
| Target (index) | `products` | seed |
| Template name | `multi-match-title-boost-v1` | seed |
| Query-set name | `top-product-searches-q4-2025` | seed |
| Judgment-list name | `acme-products-relevance-2025-12` | seed |
| Study name | `tune-product-title-boost-baseline-${uuid6}` | seed slug + collision suffix |
| `objective` | `{metric: 'ndcg', k: 10, direction: 'maximize'}` | seed default |
| `search_space` | `{params: {title_boost: {type: 'float', low: 0.5, high: 10, log: true}}}` | matches seed's title-boost-baseline framing |

**Self-contained guarantee.** The spec MUST NOT depend on `make seed-demo` having run; it just borrows the scenario's naming + field values. Recommended implementation: add a new `seedAcmeProductsChain()` wrapper to [`ui/tests/e2e/helpers/seed.ts`](../../../../ui/tests/e2e/helpers/seed.ts) that composes the existing `seedCluster` / `seedQuerySet` / `seedTemplate` / `seedJudgmentList` primitives with the acme naming. **Do NOT modify `seedFullChain`** — it's shared by other E2E specs and the `e2e-*` naming is the right default for tests that don't display the chain (only those that screenshot it need realistic names). The wrapper approach keeps it DRY for future realistic-data guides (corp-docs, news, jobs) without breaking existing test expectations.

### Capability 2 — Caption updates to teach the new target picker

After the regen, update [`ui/public/guides/06_create_and_monitor_study/metadata.json`](../../../../ui/public/guides/06_create_and_monitor_study/metadata.json) caption for slide 03 to mention the new dropdown behavior:

> "Click **Create study** to open the wizard. Step 1 asks for a cluster and target. The target picker is now a dropdown populated from the cluster's index list (scoped by the cluster's `target_filter` if set); if your operator-supplied glob is restrictive or the cluster returns 403, click **Enter manually** to fall back to the free-text input."

Also bump `estimated_time` if the captions get materially longer, and update [`ui/src/components/guides/guide-types.ts`](../../../../ui/src/components/guides/guide-types.ts) `GUIDE_REGISTRY` for guide 06 if the title/description/estimatedTime change (the `guide-registry.test.ts` parity test enforces this — see PR #177 commit `deeae82` for the precedent).

### Capability 3 (optional) — Audit guide 06's tutorial-first-study sibling

[`docs/08_guides/tutorial-first-study.md`](../../../08_guides/tutorial-first-study.md) (and the broader walkthrough catalog) may also describe Step 1 in prose. If the prose references "type the target name" or similar, update to mention the dropdown + manual-mode fallback.

## Scope signals

- **Backend:** N/A.
- **Frontend:** N/A (no source code change — just a regenerated PNG).
- **Migration:** N/A.
- **Config:** N/A.
- **Audit events:** N/A.

## Relationship to other work

- **Builds on** [`feat_create_study_target_autocomplete`](../feat_create_study_target_autocomplete/) — must merge first.
- **Pattern from** [`chore_form_dropdown_guide_screenshot_refresh`](../../00_overview/implemented_features/2026_05_19_chore_form_dropdown_guide_screenshot_refresh/) — PR #154, same approach.
