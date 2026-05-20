# Re-enable `studies-create-validation.spec.ts` once create-study-modal click-target stabilizes

**Date:** 2026-05-19 (implemented 2026-05-20)
**Status:** **Implemented — PR #161 (squash `0879df2`)**, merged 2026-05-20. Picked Option B (Playwright-side dispatchEvent fix) — see "What actually shipped" section at the bottom for the final diagnosis (which corrected the original Origin diagnosis).
**Origin:** PR #157 ran Playwright smoke lane against real backend; the new `ui/tests/e2e/studies-create-validation.spec.ts` failed with `locator.click: Test timeout of 30000ms exceeded.` on the cluster trigger button. The trigger toggled disabled → enabled → disabled as TanStack Query refetched the cluster list, and Playwright's auto-wait on element stability never converged. Skipped with `test.skip(...)` so the rest of the chore could merge; the contract this spec was meant to lock is already covered by `backend/tests/contract/test_studies_error_codes.py` + `ui/src/__tests__/components/studies/create-study-modal.client-validation.test.tsx`, so the deferral is parity-belt, not coverage gap.
**Depends on:** [`chore_create_study_wizard_polish`](../2026_05_20_chore_create_study_wizard_polish/) merging (the E2E lives in its branch)

## Problem

The Playwright smoke lane runs every `ui/tests/e2e/*.spec.ts` against a real-backend stack. The create-study modal's Step-1 cluster trigger (rendered by [`EntitySelect`](../../../../ui/src/components/common/entity-select.tsx)) shows `disabled` while `useClusters` is fetching, then becomes enabled once data arrives. In `studies-create-validation.spec.ts` the chained queries (`useClusters` + `useClusterSchema` + `useQuerySets` + `useJudgmentLists` + `useTemplates`) and TanStack Query's refetching cycle cause the button's `aria-disabled` to flip back and forth several times within the first second of modal open. Playwright's `click()` auto-waits for the target to be stable + enabled; the flipping kept it un-clickable for the full 30-second test timeout.

`ui/tests/e2e/query_sets_create.spec.ts` does the same `.click()` on its cluster trigger without issue — the create-query-set modal only depends on `useClusters`, no chained queries. So the failure mode is specific to multi-query forms like the create-study modal.

## Proposed capabilities

### Option A — Stabilize the EntitySelect disabled gating

- Either suppress the disabled state during background refetches (only show disabled on initial load), or remove the disabled prop entirely and let users open the dropdown even while loading (it just shows a "Loading…" sentinel until data arrives).
- This is a generic improvement to `EntitySelect` and benefits every form that uses it; risk is the EntitySelect-discipline test guard at `ui/src/__tests__/components/common/entity-select-discipline.test.ts` may need an update.

### Option B — E2E-side fix: wait for the modal's network to settle

- Before the first `.click()`, wait for either `page.waitForLoadState('networkidle')` or an explicit `page.waitForResponse` per backing query.
- Less invasive than Option A but every multi-query modal E2E pays the same boilerplate. Brittle if a new query gets added to the modal later.

### Option C — Drop the E2E entirely

- Argument: the client-side validator is fully covered by `create-study-modal.client-validation.test.tsx` (5 cases). The server-side rejection envelope is covered by `test_studies_error_codes.py` (contract test). The E2E would only add cross-layer parity — which is value, but bounded.
- Cleanest if Option A is blocked on a UX decision.

Recommended: **Option A** if the EntitySelect-discipline test allows the change, otherwise **Option B**. Either way the spec re-enables with a 1-line `test.skip()` removal.

## Scope signals

- **Backend:** none.
- **Frontend:** ~30 LOC in `ui/src/components/common/entity-select.tsx` for Option A, or ~5 LOC of waits in `ui/tests/e2e/studies-create-validation.spec.ts` for Option B.
- **Migration:** none.
- **Config:** none.
- **Audit events:** N/A.

## Why deferred

Fixing the flakiness was estimated >60min of iteration against the real-backend smoke lane (the failure mode requires a CI cycle to reproduce; the local stack doesn't always exhibit it). The PR was scope-clean otherwise and the coverage gap is parity-only, so skipping the spec and capturing this idea was cheaper than holding the PR for an investigation that needed CI cycles.

## Relationship to other work

- Originating chore: [`chore_create_study_wizard_polish`](../2026_05_20_chore_create_study_wizard_polish/)
- Adjacent to: any E2E that opens a multi-query form modal (only `create-study` today; future builder UIs in `feat_create_study_search_space_builder` will likely hit the same pattern).

## What actually shipped (2026-05-20)

The original Origin diagnosis ("trigger toggled disabled → enabled → disabled as TanStack Query refetched") was **wrong**. Two CI cycles on PR #161 surfaced the real cause:

1. First cycle (`.click()`) — failed exactly like the original chore_create_study_wizard_polish run.
2. Second cycle (added `await expect(trigger).toBeEnabled({ timeout: 10_000 })` before each click) — `toBeEnabled` passed (the button was NOT disabled), but `.click()` STILL timed out at 30s with `"60 × waiting for element to be visible, enabled and stable"`. The button was enabled but its **bounding box** kept shifting across animation frames.
3. Third cycle (swapped `.click()` → `.dispatchEvent('click')` on the trigger) — passed cleanly: 63/63 Playwright tests green including the previously-skipped spec.

Real cause: Radix Dialog's focus-trap + the modal's 5 chained TanStack queries on first open cause micro-layout shifts (a few px) on every animation frame. Playwright's `_isStable` heuristic compares two consecutive frames' bounding boxes and never sees them converge. The element IS reachable; only the heuristic is over-eager.

The fix:

- New `pickEntity(page, triggerTestId, optionName)` helper at `ui/tests/e2e/studies-create-validation.spec.ts` factors the 4 "click trigger → click option" pairs into one place.
- Helper gates the trigger click on `toBeEnabled()` (precondition — cheap insurance) then uses `trigger.dispatchEvent('click')` to fire a synthetic event that bypasses the actionability check.
- Option click stays as `.click()` — by the time the Radix popover renders, layout has settled.

Same pattern as PR #154's `query-set` walkthrough guide fix (which Gemini surfaced in its review of that PR). Worth remembering as the canonical workaround for "element-is-enabled-but-not-stable" failures in Radix-Dialog-hosted forms.

Gemini Code Assist's review on PR #161 caught a separate fragility: `pickEntity` originally typed `optionName: RegExp` and callers wrapped `new RegExp(name)`. If a seed helper ever generates a name with regex specials (parens, `+`, `.`), the test would silently break. Accepted across 4 call sites — type is now `string | RegExp` and call sites pass plain strings.
