# Bug fix — bug_e2e_target_dropdown_flake

**Source idea:** [idea.md](./idea.md)
**Branch:** `bug/e2e-target-dropdown-flake`
**Type:** bug fix — medium (test infrastructure; ~10 LOC change)
**Date:** 2026-05-21

## Problem

The new dropdown-mode E2E spec `studies-create-target-dropdown.spec.ts` (authored during `feat_create_study_target_autocomplete` Story F2) times out at 60–120s. It was checked in as `test.skip` with a captured idea file blaming Radix popover Playwright interaction. The dropdown happy path lacks browser-layer verification end-to-end; AC-1/AC-6/AC-7 rely on unit + integration tests instead.

## Reproduction

Un-skip + run against the local stack (`make up`):

```bash
cd ui && npx playwright test tests/e2e/studies-create-target-dropdown.spec.ts --timeout=60000 --trace=on
# fails: "Test timeout of 60000ms exceeded" — element step-next "is not enabled" (retries every 500ms for 60s)
```

The Playwright trace (`test-results/.../trace.zip`) shows the hang is at `call@74 = Frame.click('step-next')` after reaching Step 4 — NOT at the Radix popover interaction the idea hypothesized.

## Root cause

**Owning layer:** test infrastructure (the spec file itself, not product code).

The idea file's 3 hypotheses (data-testid caching across render branches, TanStack staleTime serving cached empty data, Radix focus-trap interactions) were **all wrong** — speculation written without a trace. The actual failure:

- Origin: [`create-study-modal.tsx:376-383`](../../../../ui/src/components/studies/create-study-modal.tsx#L376-L383) — `stepValid(s=3)` requires `values.name` (Study name) AND parseable `search_space_text` for Step-4 Next to enable.
- Propagation: [`studies-create-target-dropdown.spec.ts:140-141`](../../../../ui/tests/e2e/studies-create-target-dropdown.spec.ts#L140-L141) (pre-fix) clicked `step-next` on Step 4 with the Study-name field still empty.
- Propagation: [`studies-create-target-dropdown.spec.ts:144-145`](../../../../ui/tests/e2e/studies-create-target-dropdown.spec.ts#L144-L145) (pre-fix) filled the Study-name AFTER the Step-4 → Step-5 click — but the click never landed because the button was disabled.

Why the idea's hypotheses looked plausible: Playwright's auto-cleanup unwound the page state by the time the 60s timeout fired, so the error-context.md page snapshot showed the studies-list page (NOT the modal). Without the trace, it looked like the modal had closed unexpectedly during the dropdown interaction. The trace falsifies this — steps 1-3 (cluster + target dropdown + query-set + judgment-list + template) all succeed cleanly.

Secondary bug discovered during the fix: the assertion `expect(created.target).toBe(seededTargets[1])` was reading `.target` off the `StudySummary` list response, which omits the field (only `StudyDetail` carries it). Even if Step-4 had advanced, the test would have failed with `expect(undefined).toBe('e2e-target-alpha-...')`.

## Fix design (locked decisions)

1. **Fill Study name on Step 4 before clicking next-to-Step-5.** Cites [`create-study-modal.tsx:376-383`](../../../../ui/src/components/studies/create-study-modal.tsx#L376-L383) `stepValid` semantics + precedent in [`studies-create-builder.spec.ts:130`](../../../../ui/tests/e2e/studies-create-builder.spec.ts#L130) which fills name on Step 4 before advancing.
2. **Fill Max trials on Step 5 before submitting.** Cites [`create-study-modal.tsx:384-390`](../../../../ui/src/components/studies/create-study-modal.tsx#L384-L390) — `stepValid(s=4)` requires `max_trials > 0` OR `time_budget_min > 0`. Same precedent at [`studies-create-builder.spec.ts:147`](../../../../ui/tests/e2e/studies-create-builder.spec.ts#L147).
3. **Fetch StudyDetail (not StudySummary) for the target assertion.** Cites [`backend/app/api/v1/schemas.py:109-119`](../../../../backend/app/api/v1/schemas.py#L109-L119) — `ClusterSummary`-style summary models intentionally omit `target` for list-view brevity; `StudyDetail` is the full shape. The fix swaps the assertion target to `/api/v1/studies/{id}` detail.
4. **Keep the spec in its own file** (not merged into `studies-create-builder.spec.ts`). Distinct test intent (target-DROPDOWN happy path vs builder happy path).
5. **Rewrite the doc-block comment** to drop the "currently skipped — see follow-up idea" lore. The test now passes; the comment describes what the test exercises, not why it was skipped.

## Regression test plan

The fixed test itself IS the regression guard — fail-on-main, pass-on-branch:

| Layer | Path | What it asserts |
|---|---|---|
| E2E (real-backend) | `ui/tests/e2e/studies-create-target-dropdown.spec.ts` | Pick a target from the Step-1 dropdown → walk the full create-study wizard → assert the persisted `study.target` matches the dropdown-picked index |

Stability: 3 consecutive local runs pass in 1.5–2.9s.

## Rollout

None — test-only change. No production code touched. No migration. No config.

## Tangential observations

- [bug_get_schema_unhandled_connect_error](../bug_get_schema_unhandled_connect_error/idea.md) — work shipped via PR #165 squash `bd4516a` but the folder is still in `planned_features/`. Bundled fix: move folder to `implemented_features/2026_05_20_bug_get_schema_unhandled_connect_error/` in the same PR as this fix (user direction: "fix both now").
