# Bug idea: vitest 4.1.6 + jsdom 29.1.1 — 31 pre-existing vitest failures from `window.localStorage` undefined

**Date noticed:** 2026-05-24
**Origin:** Pre-push gate during impl-execute of `feat_home_demo_reseed_endpoint`. Running `pnpm vitest run` on the worktree reported `733 passed, 31 failed`, all 31 failures clustered in 4 files all touching `window.localStorage`. Confirmed pre-existing by stashing the feature branch changes (the failures persisted on the baseline).
**Status:** open.

## Problem

`pnpm vitest run` on `feature/home-demo-reseed-endpoint` (and `main`) reports the following 4 files failing with the same root error:

```
TypeError: Cannot read properties of undefined (reading 'clear')
  at src/__tests__/lib/safe-local-storage.test.ts:37:25
  at src/__tests__/components/guides/guide-viewer.test.tsx
  at src/__tests__/components/guides/markdown-doc.test.tsx
  at src/__tests__/components/common/data-table-col-vis-density.test.tsx
```

Each failure stems from `window.localStorage` being `undefined` in the jsdom test environment, surfaced via Node runtime warnings:

```
(node:96720) ExperimentalWarning: localStorage is not available because
  --localstorage-file was not provided.
```

The warning comes from **Node's** experimental `localStorage` flag, not jsdom — vitest 4.1.6's jsdom integration appears to be deferring storage creation in a way that races test setup teardown (calls to `window.localStorage.clear()` / `removeItem()` in `beforeEach` / `afterEach` find the property missing).

## Why deferred

Out of scope for `feat_home_demo_reseed_endpoint`. The PR's new vitest tests (`reset-demo-state-button.test.tsx`, `start-here-checklist.test.tsx`) do NOT touch `window.localStorage` and pass cleanly (20/20). Fixing the underlying jsdom/vitest infra is a separate concern requiring either:

* Pinning vitest/jsdom back to a known-good pair (vitest 3.x / jsdom 25.x).
* Adding an explicit `setupFiles` shim that initializes `window.localStorage` before each suite.
* Upgrading vitest to a fix release that resolves the Node 22 localStorage race.

## Suggested next step

Triage as a `bug_` and run `/bug-fix` on this folder. The fix is bounded but requires deciding between the three remediation paths above (deps decision = product-ish, fits the "/bug-fix" rubric). Estimated work: <2h once a path is picked.

## References

* `ui/src/__tests__/lib/safe-local-storage.test.ts:37` — first failure site.
* `ui/vitest.config.ts` — environment: jsdom, globals: true.
* `ui/package.json` — `vitest@4.1.6`, `jsdom@29.1.1`.
