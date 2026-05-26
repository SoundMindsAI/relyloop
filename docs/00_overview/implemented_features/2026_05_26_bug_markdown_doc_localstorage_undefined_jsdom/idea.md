# Bug: `markdown-doc.test.tsx` fails on `localStorage.removeItem` (undefined `localStorage`)

**Date:** 2026-05-24
**Status:** Closed 2026-05-26 — subset of [`bug_vitest_jsdom_localstorage_failures`](../2026_05_26_bug_vitest_jsdom_localstorage_failures/idea.md) (same root cause; this folder captured a 3-test slice when surfaced during `feat_digest_executable_followups` Story 5.1 vitest sweep). Failures stopped reproducing on main between filing and 2026-05-26 (verified by 3 consecutive `pnpm test` runs at 860/860 on commit `2d2328b1`); a defensive `window.localStorage` shim landed in `ui/src/__tests__/setup.ts` so the race can't return undetected.

## Origin

Captured during feat_digest_executable_followups implementation. Running the
full UI test suite (`pnpm test`) surfaces three pre-existing failures in
`ui/src/__tests__/components/guides/markdown-doc.test.tsx`:

- `wide-column toggle flips data-wide attribute`
- `hydrates text-size from localStorage on mount`
- `View on GitHub link points at the source path under docs/08_guides/`

All three fail in the `afterEach` cleanup:

```
TypeError: Cannot read properties of undefined (reading 'removeItem')
 ❯ src/__tests__/components/guides/markdown-doc.test.tsx:37:25
     37|     window.localStorage.removeItem('relyloop.guide-viewer.text-size');
```

Verified pre-existing on `main` via `git stash` + re-run.

## Problem

The afterEach hook unconditionally calls
`window.localStorage.removeItem(...)` after each test, but `window.localStorage`
is `undefined` in the test environment by the time the hook runs — either the
jsdom env was torn down early OR the test setup never installed a
`localStorage` polyfill for this file.

The check `if (typeof window !== 'undefined')` is necessary but not
sufficient — `window` exists in jsdom but `window.localStorage` can still
be undefined depending on the jsdom config / test ordering.

## Why deferred

Out of scope for current PR (feat_digest_executable_followups touches
digest follow-ups, not guide markdown rendering). Fix is small (one-line
defensive check) but unrelated to the active feature surface.

## Proposed fix

Wrap the removeItem call in a `typeof` guard:

```ts
if (typeof window !== 'undefined' && window.localStorage) {
  window.localStorage.removeItem('relyloop.guide-viewer.text-size');
}
```

Or hoist the cleanup into a `beforeEach`/`afterEach` pair that uses
`vi.stubGlobal('localStorage', { ... })` for deterministic isolation.

## Scope signals

- Frontend test-only change
- No production code modified
- No migration
- No new dependency
- Verified by re-running `pnpm vitest run src/__tests__/components/guides/markdown-doc.test.tsx`
