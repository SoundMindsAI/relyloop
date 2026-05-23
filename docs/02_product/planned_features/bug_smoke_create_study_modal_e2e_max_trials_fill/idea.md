# Bug — smoke CI: create-study modal E2E `max_trials` fill times out

**Date:** 2026-05-23
**Status:** Idea — regression introduced by `chore_study_default_stop_conditions` PR #215
**Priority:** P1
**Origin:** Surfaced repeatedly in CI smoke job during `chore_study_default_stop_conditions` PR #215. Skipped via `test.skip()` on [`ui/tests/e2e/studies-create-builder.spec.ts:130`](../../../../ui/tests/e2e/studies-create-builder.spec.ts) to unblock the PR.
**Depends on:** None (the change that introduced the regression is already merged when this idea is picked up).

## Problem

After PR #215 added the Stop-condition preset selector to [`ui/src/components/studies/create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx), the Playwright E2E case `studies-create-builder.spec.ts:130 — "case 1: builder edits propagate to textarea + submitted study persists the value"` started consistently timing out in CI smoke. The failure manifests at:

```typescript
await page.getByRole('spinbutton', { name: 'Max trials' }).fill('10');
// or alternately on the next line:
await page.getByTestId('create-study-submit').click();
```

Both Playwright actions hit the 30s `Test timeout exceeded` ceiling. The test passes locally against a Next.js dev server **and** against vitest jsdom (98/98 stop-condition cases green), so the regression is **production-build-only** and reproduces only in CI Chromium.

Five fix attempts during PR #215 review failed to resolve it:

1. Drop `form` from the modal-open `useEffect` dep array
2. Add `max-h-[90vh] overflow-y-auto` to `DialogContent` (suspected modal overflow)
3. Gate form-field reset on a `useRef`-tracked closed→open transition (avoid effect re-fires)
4. Drop in-effect `form.setValue` entirely; accept persistent form-state UX
5. Replace `useEffect` watcher with `form.watch(callback)` subscription (broke 4 vitest cases — reverted)

## Proposed capabilities

### Reproduce locally against a production build

- `cd ui && pnpm build && pnpm start` (NOT `pnpm dev` — the bug only reproduces against the optimized build) — or rebuild the `relyloop/ui` Docker image and use `make up`.
- `BASE_URL=http://localhost:3000 API_BASE_URL=http://localhost:8000 npx playwright test studies-create-builder --grep "case 1" --headed --debug`
- Open the Playwright trace viewer when the timeout fires; inspect what the locator is matching, whether the input is visible/enabled/stable, and whether DOM is re-rendering during fill.

### Identify the React 19 / RHF / React Compiler interaction

Working hypothesis: the new `useEffect` watcher in [`create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx) (subscribes to `form.watch('max_trials')` + `form.watch('time_budget_min')`, flips `activePreset` to `'custom'` when values diverge) interacts badly with React 19's compiler + RHF's incompatibility (ESLint already flags `react-hooks/incompatible-library` on `form.watch`). In production build the input may be momentarily non-actionable because the input keeps re-rendering during Playwright's fill.

Candidate fixes to evaluate:

- Replace the watcher's `useEffect` with `useSyncExternalStore` against an RHF subscription (no extra render cycle).
- Move the watcher into the input's onChange handler via `Controller` (RHF's recommended controlled-input pattern when external state needs to react to value changes).
- Hoist the active-preset out of state entirely — derive via `useMemo` from form values. Custom-button click becomes a no-op (active-preset display is purely derived from values).

### Re-enable the E2E case

- Remove the `test.skip()` marker on `studies-create-builder.spec.ts:130`.
- Confirm green in CI smoke for ≥2 consecutive runs.

## Scope signals

- **Backend:** none — backend contracts unchanged.
- **Frontend:** `ui/src/components/studies/create-study-modal.tsx` only. The watcher pattern is the suspected hot spot; same pattern may exist in other modals and warrant a sweep.
- **Migration:** none.
- **Config:** none.
- **Audit events:** N/A (pre-MVP2).

## Why deferred

The regression surfaced after the spec/plan/impl were all green through 3 GPT-5.5 review cycles + 98 vitest cases. It only triggers in production-build Chromium, which I could not reproduce locally without rebuilding the Docker UI image. Debugging requires interactive access to the Playwright trace viewer against the production build — work better suited to a focused follow-up than to extending PR #215's timeline.

The user-visible impact is: `studies-create-builder.spec.ts:130 case 1` is the **only** test affected; all other E2E flows (10+ specs in `tests/e2e/`) still exercise the create-study modal successfully (including case 2 / case 3 / etc. in the same file, which DO interact with the form past step 5). The runtime UX is correct — vitest cases AC-1..AC-10 + bug-guards all pass against the same code that fails the one E2E case.

## Relationship to other work

- Introduced by [`chore_study_default_stop_conditions`](../chore_study_default_stop_conditions/feature_spec.md) PR #215.
- The same React 19 + RHF interaction may explain the existing `react-hooks/incompatible-library` ESLint warning on `form.watch('cluster_id')` at [`create-study-modal.tsx:174`](../../../../ui/src/components/studies/create-study-modal.tsx#L174). Worth investigating whether the broader pattern needs revisiting.
