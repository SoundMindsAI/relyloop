# Regenerate 4 walkthrough guides whose screenshots include EntitySelect-migrated modals

**Date:** 2026-05-18
**Status:** Idea — captured during `chore_form_dropdown_primitive` post-implementation guide-impact assessment.
**Origin:** [`chore_form_dropdown_primitive`](../chore_form_dropdown_primitive/feature_spec.md) PR (pending) migrates four form modals to the new `<EntitySelect>` primitive. Four walkthrough guides at `ui/public/guides/<NN>/*.png` ship screenshots that include the migrated modals — those screenshots will diverge from the live UI after the PR merges.
**Depends on:** `chore_form_dropdown_primitive` PR merged + dev stack runnable (`make up`).

## Problem

Each affected guide has a Playwright spec at `ui/tests/e2e/guides/*.spec.ts` that captures screenshots when run against the real backend. The PR's UI changes produce different screenshots:

| Guide | Modal | Visual diff from PR |
|---|---|---|
| [`01_register_first_cluster`](../../../../ui/tests/e2e/guides/01_register_first_cluster.spec.ts) | `register-cluster-modal.tsx` | Config-repo field is now always visible with an empty-state CTA when no repos exist (was conditionally hidden when `configRepos.data.length === 0`). |
| [`04_create_query_set`](../../../../ui/tests/e2e/guides/04_create_query_set.spec.ts) | `create-query-set-modal.tsx` | Cluster field is now a dropdown with health-status dots instead of a UUID `<Input>`. Label changes from "Cluster ID" to "Cluster". |
| [`06_create_and_monitor_study`](../../../../ui/tests/e2e/guides/06_create_and_monitor_study.spec.ts) | `create-study-modal.tsx` | Cluster picker (step 1) renders with health-status dots before each cluster name. Visually subtle but present. Other 3 FK pickers unchanged in appearance. |
| [`09_generate_judgments_llm`](../../../../ui/tests/e2e/guides/09_generate_judgments_llm.spec.ts) | `generate-judgments-dialog.tsx` | Template picker is now an `<EntitySelect>` (no health dots — templates have no `health_check`). Visual diff is near-zero; included for completeness. |

The screenshots aren't structurally broken (no missing buttons or relabeled testids). They're just **outdated** — they show the pre-migration UI. New tenants following the guides will see UI that doesn't match the screenshots, which is mildly confusing.

## Proposed capabilities

Run `/guide-gen <NN> --regen` for each of the four guides:

```bash
/guide-gen 01_register_first_cluster --regen
/guide-gen 04_create_query_set --regen
/guide-gen 06_create_and_monitor_study --regen
/guide-gen 09_generate_judgments_llm --regen
```

Each invocation requires:

1. Running dev stack (`make up`).
2. Playwright installed (`pnpm exec playwright install` in `ui/`).
3. A registered local cluster + a query set + a judgment list + a template (the guides' setup steps assume these exist).

The output replaces PNG files under `ui/public/guides/<NN>/` and re-runs the cross-model visual review (per [`docs/01_architecture/ui-architecture.md` §"Guide generation"](../../../01_architecture/ui-architecture.md) if it exists; otherwise see the `guide-gen` skill).

## Scope signals

- **Backend:** none.
- **Frontend:** none beyond regeneration.
- **Migration:** none.
- **Config:** none.
- **Audit events:** none.
- **Tests:** the existing Playwright specs at `ui/tests/e2e/guides/*.spec.ts` continue to pass — the data-testids the specs assert on were preserved by the PR. Only the captured PNG outputs change.
- **Docs:** the `docs/08_guides/` markdown content does NOT need to change — only the screenshots embedded in the rendered guides do.

## Why deferred

The remote execution environment that runs `/impl-execute` doesn't have Docker, doesn't have the dev stack, and can't run Playwright against a live backend. Guide regeneration is inherently an operator-local task — it must run on a developer's laptop (or in a CI runner with the full stack).

This is the same deferral the `feat_data_table_primitive` (PR #126) implementation surfaced for its 9 migrated tables: stale screenshots after a UI primitive landed, regenerate when a maintainer next runs the dev stack locally.

## Recommended pipeline path

`/impl-execute --ad-hoc` against the four `/guide-gen` invocations is the right shape. Effort: 30-60 minutes once the dev stack is running. No spec needed; the regeneration mechanism is fully documented in the `guide-gen` skill.

## Relationship to other work

- **Parent:** [`chore_form_dropdown_primitive`](../chore_form_dropdown_primitive/feature_spec.md) — the migration that made the screenshots stale.
- **Sibling precedent:** PR #126 (feat_data_table_primitive) likely needed similar guide regeneration — confirm whether that PR's follow-up was completed or if there's an open guide-regeneration backlog (`ls docs/02_product/planned_features/ | grep guide`).
