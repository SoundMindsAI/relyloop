# chore_e2e_seed_acme_helper_dead idea is obsolete — close or update it

**Date:** 2026-05-23
**Status:** Idea — surfaced during `chore_migration_test_head_brittleness` `/idea-preflight` pick (2026-05-23)
**Priority:** P2 — doc-only cleanup; no behavioral impact. 5–10 LOC + a coverage-audit refresh. (Note: dashboard regen at [`scripts/build_mvp1_dashboard.py:240-245`](../../../../scripts/build_mvp1_dashboard.py#L240) only recognizes P0/P1/P2/Backlog and coerces anything else to P2; an earlier draft used "P3" which the dashboard rendered as P2 anyway. Setting to P2 explicitly to keep the idea-file and dashboard tier columns aligned — surfaced by Gemini Code Assist on PR #220.)
**Origin:** While running `/idea-preflight` against [`chore_e2e_seed_acme_helper_dead/idea.md`](../chore_e2e_seed_acme_helper_dead/idea.md) to pick a non-overlapping feature for `feat_auto_followup_studies`, I discovered the idea's central premise is contradicted by current code: `seedAcmeProductsChain` now has a real Playwright caller at [`ui/tests/e2e/guides/06_create_and_monitor_study.spec.ts:28`](../../../../ui/tests/e2e/guides/06_create_and_monitor_study.spec.ts#L28) (`import { seedAcmeProductsChain } from '../helpers/seed';` and `await seedAcmeProductsChain();` at line 34). The spec uses the chain's `studyId` and `studyName` to render guide screenshots against a realistic "Acme Products" seeded study.
**Depends on:** None.

## Problem

[`chore_e2e_seed_acme_helper_dead/idea.md`](../chore_e2e_seed_acme_helper_dead/idea.md) (dated 2026-05-21) proposed two paths:

- **Path A — Delete the helper** (recommended in the idea, "probably correct").
- **Path B — Wire a spec that uses it.**

Path B effectively shipped between 2026-05-21 and 2026-05-23 (commit `2cbcb93b chore(guides): regen guide 06 with realistic seed data + new target ...`). The guide-06 walkthrough spec imports the helper, calls it once per test run, and asserts the resulting `/studies/[id]` page renders. The helper is no longer dead code.

Two stale artifacts result:

1. **`docs/00_overview/planned_features/chore_e2e_seed_acme_helper_dead/idea.md`** — still describes the helper as "0 Playwright spec callers" (line 6 + 14–16) and recommends Path A (delete) without acknowledging Path B has shipped.
2. **[`ui/tests/e2e/helpers/coverage-audit.md`](../../../../ui/tests/e2e/helpers/coverage-audit.md)** — the §"Coverage matrix" table still reports `seedAcmeProductsChain` as `0 specs — currently uncalled` and the §"Gaps" section + §"Verdict" both claim the helper is dead code.

Neither is load-bearing, but both surface in `/pipeline status` / `MVP1_DASHBOARD.md` and confuse the next infra-sweep agent.

## Proposed capabilities

Two options:

### Option A — Close the idea as "won't do / superseded by Path B"

Add a one-block update to the top of [`chore_e2e_seed_acme_helper_dead/idea.md`](../chore_e2e_seed_acme_helper_dead/idea.md):

```
**Status (updated 2026-05-23):** Closed — Path B effectively shipped via guide-06 spec
(`ui/tests/e2e/guides/06_create_and_monitor_study.spec.ts`, commit `2cbcb93b`,
2026-05-22). The helper now has a real caller. No further action needed beyond
refreshing `coverage-audit.md` to reflect the new coverage state.
```

Refresh `ui/tests/e2e/helpers/coverage-audit.md`:
- Update the table row for `seedAcmeProductsChain` from `0 specs` to `guides/06_create_and_monitor_study.spec.ts`.
- Remove the §"Gaps" subsection (or replace it with `## Gaps\n\nNone as of 2026-05-23.`).
- Refresh the §"Verdict" sentence count from "8 of 9" to "9 of 9".

### Option B — Move the folder to `implemented_features/` with a `pipeline_status.md` shim

Per [`docs/00_overview/planned_features/feature_templates/README.md`](../feature_templates/README.md) folder lifecycle, ideas that genuinely ship via another feature can be moved to `docs/00_overview/implemented_features/2026_05_22_chore_e2e_seed_acme_helper_dead/` with a tiny `pipeline_status.md` saying "shipped via `feat_pr_metric_confidence`-aware guide-06 spec, PR #X." This is more ceremony than Option A for very little extra discoverability win.

**Recommendation:** Option A. The original idea was correctly captured as a small chore; it just got OBE'd by adjacent work. A one-paragraph status update + a coverage-audit refresh is the right ceremony for that shape.

## Scope signals

- **Backend:** none.
- **Frontend:** none (no spec edits — the spec is already correct).
- **Migration:** none.
- **Config:** none.
- **Audit events:** N/A.
- **Tests:** none.
- **Docs:** ~10 LOC across two files (`chore_e2e_seed_acme_helper_dead/idea.md` + `ui/tests/e2e/helpers/coverage-audit.md`).

## Why deferred

Surfaced during the `chore_migration_test_head_brittleness` `/idea-preflight` run, while the agent was looking for a feature that wouldn't overlap with `feat_auto_followup_studies`. Editing the original idea file directly on the migration-test chore's branch would mix scope across two unrelated folders (CLAUDE.md "Tangential discoveries" rubric: "Cross-subsystem mixing in one PR breaks reviewability"). Captured here so the next infra-sweep agent has a clean target.

## Relationship to other work

- **Originating idea:** [`chore_e2e_seed_acme_helper_dead`](../chore_e2e_seed_acme_helper_dead/idea.md) — the one this captures was OBE'd.
- **Source of OBE:** [`chore_guide_06_screenshot_refresh_target_picker`](../../../00_overview/implemented_features/2026_05_21_chore_guide_06_screenshot_refresh_target_picker/idea.md) — recommended the wrapper helper approach that became `seedAcmeProductsChain`. Now consumed by the guide-06 spec.
- **No mechanical dependency on this chore.** Any future infra-sweep can run it in any order.
