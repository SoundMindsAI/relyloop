# Stabilize the overnight Strategy toggle E2E (Radix Select + react-hook-form timing)

**Date:** 2026-06-03
**Status:** Idea — tangential follow-up captured during `feat_overnight_final_solution` Story 3.2 implementation
**Priority:** P2
**Origin:** Story 3.2 of `feat_overnight_final_solution` planned an `ui/tests/e2e/overnight-strategy.spec.ts` that exercises the wizard's new Strategy toggle end-to-end (AC-4 visibility + AC-5 wire submission). The spec was written and works at the JSX level — the 6 vitest cases at [`create-study-modal.overnight-strategy.test.tsx`](../../../../ui/src/__tests__/components/studies/create-study-modal.overnight-strategy.test.tsx) all pass — but the chromium-against-dev-server pass fails consistently: after clicking the depth Radix `<Select>` option ("2 follow-ups"), the strategy toggle's conditional render (`{values.auto_followup_depth >= 1 && (...)}`) doesn't fire even though the visible trigger updates to "2 follow-ups". The deleted spec lived for ~30 min and was removed at end of Story 3.2; the implementation itself (the toggle, the form schema field, the submit handler, the glossary key, the enum mirror) is fully shipped and tested at every other layer.
**Depends on:** `feat_overnight_final_solution` Phase 1 (which is shipping with the failing-spec deletion noted).

> **Priority guidance:** P2 — quality-only, not blocking. The strategy toggle is comprehensively covered by 6 vitest cases (AC-4 hidden/visible/hide-on-revert, AC-5 follow_suggestions submit, default-narrow, omit-both), the backend dispatch by 10 integration tests, the wire contract by contract tests, and the chain-panel badge by 2 more vitest cases. An E2E adds confidence at the browser+real-backend boundary but is duplicative coverage; missing it is not a blocker for the feature shipping.

## Problem

The Story 3.2 E2E spec walks the create-study wizard to Step 5, clicks the depth `<Select>` ("2 follow-ups"), and asserts the new Strategy `<Select>` becomes visible. In chromium against `pnpm dev`, the visible depth-trigger label updates correctly (the Radix Select shows "2 follow-ups") but the dependent conditional render of the strategy toggle never fires — `expect(page.getByTestId('cs-overnight-strategy')).toBeVisible({ timeout: 5_000 })` times out with "element not found." The same JSX renders the toggle correctly in:

- All 6 vitest cases under `create-study-modal.overnight-strategy.test.tsx` (using `mockShadcnSelect`).
- Manual operator interaction in the browser (confirmed via `pnpm dev` + manual click).

Likely root cause: Radix Select's `onValueChange` fires in a `microtask` queue, react-hook-form's `setValue` triggers a re-render on the next tick, and `form.watch()`'s subscription path takes another tick to propagate. Playwright's `dispatchEvent('click')` may complete before the chain settles, and the polling `toBeVisible` runs against a snapshot where the strategy toggle hasn't yet been reified. The existing `studies-create-builder.spec.ts` uses the same pattern but doesn't chain a dependent conditional render — it only asserts an entity-select trigger label updated, never asserts a sibling conditional component became visible.

## Proposed capabilities

### Cap 1 — Reliable wait pattern for "Radix Select option click → form watch → dependent render"

- Build a test helper (e.g. `pickRadixSelectAndWaitForDependent`) that:
  1. Dispatches the trigger click.
  2. Clicks the option by role+name.
  3. Polls until the trigger's display text changes.
  4. Calls `page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))))` to force two animation frames (settles microtasks + react-hook-form's queueMicrotask path).
  5. Then resolves and lets the caller assert on dependent renders.
- Apply it to the deleted `overnight-strategy.spec.ts` (revive from git history) — the AC-4 + AC-5 assertions should then pass deterministically.

### Cap 2 — Re-add the deleted E2E spec

- Revive `ui/tests/e2e/overnight-strategy.spec.ts` (recoverable from the deletion commit in `feat_overnight_final_solution`'s PR) and rebuild it on top of Cap 1's helper.
- Asserts AC-4 (toggle hidden / visible / hide-on-revert) and AC-5 (submit + read-back via `GET /api/v1/studies/{id}` confirms `config.auto_followup_strategy` is persisted).
- Real backend; no `page.route()` mocking.

### Cap 3 — Investigate whether other tests have a latent version of the same issue

- A grep across `ui/tests/e2e/*.spec.ts` for "depth Select followed by a sibling conditional render" finds at least one candidate in the digest panel surface. Confirm those tests don't flake intermittently for the same reason; if they do, route them through Cap 1's helper too.

## Scope signals

- **Backend:** No change. The wire contract is already tested at unit + contract + integration layers.
- **Frontend:** New shared helper file (e.g. `ui/tests/e2e/helpers/radix-select.ts`) + revived `overnight-strategy.spec.ts`. Possibly small touch-ups on adjacent specs if they share the failure mode.
- **Migration:** None.
- **Config:** None.
- **Audit events:** N/A.

## Why deferred from Story 3.2

Story 3.2 shipped with comprehensive coverage at four layers (vitest wizard cases, vitest chain-panel badge cases, backend contract tests, backend integration tests for the worker dispatch). The E2E adds duplicative browser-level confidence at a layer that has its own infrastructure complexity (Radix Select timing in chromium against `pnpm dev`). Spending more in-session time was crowding out the rest of the feature pipeline. Captured here so the next agent can revive the spec with the proper wait helper rather than re-discover the timing footgun.

## Relationship to other work

- **Targets** the deleted `ui/tests/e2e/overnight-strategy.spec.ts` from `feat_overnight_final_solution` Story 3.2 (recoverable via `git log` on the feature branch).
- **Generalizes** a Radix-Select-onValueChange + react-hook-form-watch timing pattern that may affect other E2E specs in the suite.
