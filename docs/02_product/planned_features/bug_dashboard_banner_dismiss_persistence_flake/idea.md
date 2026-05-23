# Pre-existing flake: dashboard banner "Dismiss persists across reload" test

**Date:** 2026-05-22
**Status:** Idea — surfaced during `feat_study_preflight_overlap_probe` (PR #193) smoke CI
**Priority:** P2 — the test's logic appears broken, but the production banner code is correct; the flake doesn't reflect a user-facing regression.

**Origin:** Two consecutive smoke CI runs on PR #193 (runs 26301403853 + 26302635889) failed at [`ui/tests/e2e/dashboard.spec.ts:63 "Dismiss persists across reload (FR-7, AC-3)"`](../../../../ui/tests/e2e/dashboard.spec.ts#L63), unrelated to the probe feature. Inspecting the test reveals a structural issue.

## Problem

The test, introduced by [PR #188 (`feat_home_first_run_demo_nudge`)](../../../00_overview/implemented_features/2026_05_22_feat_home_first_run_demo_nudge/), is:

```typescript
test('Dismiss persists across reload (FR-7, AC-3)', async ({ page, context }) => {
    await context.addInitScript(() => {
      window.localStorage.removeItem('relyloop.home-first-run-demo-nudge.dismissed');
    });
    await page.goto('/');
    await expect(page.getByTestId('demo-data-banner')).toBeVisible({ timeout: 10_000 });
    await page.getByTestId('demo-data-banner-dismiss').click();
    await expect(page.getByTestId('demo-data-banner')).toBeHidden();
    await page.reload();
    // Banner stays hidden after reload because localStorage persisted.
    await expect(page.getByTestId('demo-data-banner')).toBeHidden();
});
```

`context.addInitScript` registers a script that runs on **every** new page initialization, **including** `page.reload()`. The script does `localStorage.removeItem('...dismissed')`. After reload:

1. The init script runs FIRST → clears the `dismissed` flag from localStorage.
2. React hydrates → `useSyncExternalStore`'s client snapshot reads `safeLocalStorageGet('dismissed')` → returns `null` → banner state = NOT dismissed.
3. Banner renders.
4. Test asserts `toBeHidden()` → fails.

The test passed on its merge SHA (21325432) only by virtue of an init-script-vs-hydration race that happens to land the other way on different runners.

## Why this surfaced on PR #193

Coincidence — PR #193 didn't touch any frontend code or the banner. The smoke job's two failed runs both landed the race the wrong way. Two prior consecutive failures of the SAME test on an unrelated PR strongly suggest the underlying logic is broken, not just flaky.

## Proposed fix (Option A — locked)

Replace the init-script approach with explicit per-test localStorage management that doesn't fight the test's own assertions:

```typescript
test('Dismiss persists across reload (FR-7, AC-3)', async ({ page }) => {
    await page.goto('/');
    await page.evaluate(() => window.localStorage.removeItem('relyloop.home-first-run-demo-nudge.dismissed'));
    await page.reload();  // fresh state, no init script interference
    await expect(page.getByTestId('demo-data-banner')).toBeVisible({ timeout: 10_000 });
    await page.getByTestId('demo-data-banner-dismiss').click();
    await expect(page.getByTestId('demo-data-banner')).toBeHidden();
    await page.reload();
    // No init script clears the flag; banner stays hidden via localStorage.
    await expect(page.getByTestId('demo-data-banner')).toBeHidden();
});
```

This preserves the test's user-facing assertion ("banner stays hidden after reload because dismissal persisted") and uses real browser interactions throughout — consistent with [CLAUDE.md](../../../../CLAUDE.md) "E2E Testing Rules": *"must exercise the browser layer. Use Playwright's `page` object for real browser interactions (navigate, fill forms, click buttons, assert DOM)."*

### Alternative considered (Option B — rejected)

Assert the banner state by querying localStorage directly post-reload (`page.evaluate(() => window.localStorage.getItem('...dismissed'))` === `'1'`), treating render-or-not as a separate concern. **Rejected** because:

1. It changes the test's intent — the AC under verification is "banner stays hidden", not "localStorage was written". An operator looking at the failing test should see the user-visible behavior breaking, not an indirect storage assertion.
2. It would let a regression slip through where localStorage is correctly written but the banner re-renders anyway (e.g. a future change to the `useSyncExternalStore` wiring that doesn't read the flag). Option A catches that; Option B doesn't.

Option B's localStorage-direct check could augment Option A as a sanity assertion, but it's not a substitute for the DOM-level "stays hidden" assertion.

## Coordinates with

- Surfaced on smoke CI for [PR #193 `feat_study_preflight_overlap_probe`](../../../00_overview/implemented_features/2026_05_22_feat_study_preflight_overlap_probe/) (merged 2026-05-22, finalized 2026-05-22) — the smoke red was rerun-tolerant and didn't block that PR's merge. Capturing this flake as a separate bug fix so the test layer gets fixed at its own pace.
