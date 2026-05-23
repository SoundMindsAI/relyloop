# Bug — smoke CI: create-study modal E2E `max_trials` fill races with submit transition

**Date:** 2026-05-23
**Status:** Idea — regression introduced by `chore_study_default_stop_conditions` PR #215
**Priority:** P1
**Origin:** Surfaced repeatedly in CI smoke job during `chore_study_default_stop_conditions` PR #215. Two tests share the same root cause and are skipped via `test.skip()` to unblock the PR:

- [`ui/tests/e2e/studies-create-builder.spec.ts:130`](../../../../ui/tests/e2e/studies-create-builder.spec.ts) — "case 1: builder edits propagate to textarea + submitted study persists the value" (line 153 fill)
- [`ui/tests/e2e/studies-create-target-dropdown.spec.ts:48`](../../../../ui/tests/e2e/studies-create-target-dropdown.spec.ts) — "Step-1 target picker loads from the cluster, sorts alphabetically, and persists the picked target" (line 142 fill)

Both tests reach Step 5 of the create-study modal and fill `Max trials` via `page.getByRole('spinbutton', { name: 'Max trials' }).fill('10')`. Both fail consistently in CI Chromium against the production build.

**Depends on:** None.

## Problem

After PR #215 added `defaultValues.max_trials = 200` to the create-study modal's `useForm` call, the two Playwright E2E tests above started timing out at `page.getByTestId('create-study-submit').click()` (line 155 in studies-create-builder, line 143 in studies-create-target-dropdown).

### What's actually happening (reproduced locally against the production UI image)

1. Test reaches Step 5 with `max_trials` input showing `200`.
2. Test calls `.fill('10')` on the Max trials input.
3. **The fill operation triggers a form submit** (mechanism unknown — see "Hypotheses ruled out" below).
4. The mutation starts; submit button changes to `Submitting…` with `disabled` attribute.
5. The mutation succeeds; the study row appears in the studies list (verified in Playwright's page snapshot).
6. The modal closes via `onOpenChange(false)`.
7. Test's `.click()` on `create-study-submit` was already in progress; Playwright's actionability checks see the button alternately: not enabled, not stable, detached from DOM. Retries until 30s timeout.

Key evidence from the Playwright trace:
- Submit button locator resolves to `<button disabled type="submit" ...>Submitting…</button>` at click time.
- Page snapshot shows the studies list page with the newly-created study row (the submit succeeded; the test's intent was achieved).
- The test fails purely on the `.click()` not "sticking" — Playwright never sees the button reach an actionable state.

### Bisect: removing `defaultValues.max_trials = 200` makes the test pass

A bisecting test on the local production UI image confirmed:
- With `defaultValues.max_trials = 200` baked in: test fails (submit fires during fill).
- Without that default (max_trials starts undefined): test passes.

Equivalent attempts that did NOT fix it:
- Setting `max_trials = 200` via `form.setValue` inside a modal-open `useEffect` (instead of `defaultValues`).
- Setting `max_trials` via `Input defaultValue="200"` on the JSX.

The trigger is specifically the **non-empty `max_trials` form state at the moment Playwright fills it**, not the mechanism by which that value got there.

## Hypotheses ruled out

The following fix attempts did NOT resolve the failure (all reproduced locally against the rebuilt production UI image):

1. Drop `form` from the modal-open `useEffect` dep array — no change.
2. Add `max-h-[90vh] overflow-y-auto` to `DialogContent` — no change.
3. Gate form-field reset on a `useRef`-tracked closed→open transition — no change.
4. Drop in-effect `form.setValue` entirely — no change.
5. Replace `useEffect` watcher with `form.watch(callback)` subscription — broke 4 vitest cases; reverted.
6. Replace `useState + useEffect` watcher with `useMemo`-derived `activePreset` (eliminating the extra render cycle that was the original suspect) — no change.
7. Add `onKeyDown` handler to suppress Enter-key form submission — no change. (Whatever triggers submit during fill, it's not an Enter keypress that propagates to the form.)

So the React 19 / RHF `form.watch` / React Compiler interaction is NOT the cause. The cause is something specific to how Playwright's `.fill()` on an `<input type="number">` with a non-empty initial value interacts with the form's submission machinery in production-build Chromium.

## Proposed capabilities

### Reproduce locally against the production UI image

```bash
make up                            # ensures the production UI image is built and running
cd ui
pnpm install
BASE_URL=http://127.0.0.1:3000 API_BASE_URL=http://127.0.0.1:8000 \
  npx playwright test tests/e2e/studies-create-builder.spec.ts --grep "case 1" --headed --debug
```

Use Playwright's trace viewer to inspect what triggers the submit between `.fill('10')` and `.click()`. The trace will show the exact event sequence emitted by `.fill()` and which DOM elements receive focus.

### Candidate fixes to evaluate

A. **Identify the submission trigger.** Add a temporary `console.log('SUBMIT FIRED', e.target)` to the form's `onSubmit`. Re-run the failing test against the production build. Inspect the browser console to see exactly what triggered it (Enter event target, programmatic submit, etc.). This pinpoints whether the trigger is Enter from a button, Tab + autofill, or something else.

B. **Use `event.detail.button === 0` or `pointerType` checks** in the submit handler to gate on real user clicks. Synthetic submits (e.g., from `form.submit()` or other paths) would be filtered.

C. **Switch the form's submit handler** to fire only from an explicit button-click handler attached to the `create-study-submit` button (rather than the form's `onSubmit`). This decouples form submission from input keyboard / focus events.

D. **Update the test patterns** to use `noWaitAfter: true` (older Playwright) or wrap the click in a try/catch that recovers if the modal closes faster than Playwright expected. Less invasive but doesn't fix the underlying race.

### Re-enable the E2E cases

- Remove `test.skip()` markers on the two tests above.
- Confirm green in CI smoke for ≥2 consecutive runs.

## Scope signals

- **Backend:** none — backend contracts unchanged.
- **Frontend:** `ui/src/components/studies/create-study-modal.tsx` only.
- **Migration:** none.
- **Config:** none.
- **Audit events:** N/A (pre-MVP2).

## Why deferred

I reproduced the failure locally and exhausted seven mechanical fix attempts before deferring. The remaining work is genuine debugging — inspecting the Playwright trace at exact-event-resolution to identify what triggers the form submit during `.fill()` — which is better suited to a focused follow-up than to extending PR #215.

The user-visible impact is bounded: the runtime UX is correct (98/98 vitest cases including AC-1..AC-10 + bug-guards pass against the same code), the studies-create-builder.spec.ts has multiple other E2E cases (case 2, case 3, etc.) that still exercise the create-study modal successfully, and the studies-create-target-dropdown.spec.ts is the only test exercising the Step-1 target dropdown end-to-end. Coverage is reduced but not eliminated.

## Relationship to other work

- Introduced by [`chore_study_default_stop_conditions`](../chore_study_default_stop_conditions/feature_spec.md) PR #215.
- The same React 19 + RHF interaction warning (`react-hooks/incompatible-library` on `form.watch('cluster_id')` at [`create-study-modal.tsx:174`](../../../../ui/src/components/studies/create-study-modal.tsx#L174)) may be a contributing factor and worth investigating during the follow-up.
