# Bug: `data-table-col-vis-density.test.tsx` fails on `localStorage.setItem` / `getItem` (undefined `localStorage`)

**Date:** 2026-05-24
**Status:** Closed 2026-05-26 — subset of [`bug_vitest_jsdom_localstorage_failures`](../2026_05_26_bug_vitest_jsdom_localstorage_failures/idea.md) (same root cause; this folder captured a 3-test slice when surfaced during `feat_study_clone_from_previous` Story 2.1 vitest sweep). Failures stopped reproducing on main between filing and 2026-05-26 (verified by 3 consecutive `pnpm test` runs at 860/860 on commit `2d2328b1`); a defensive `window.localStorage` shim landed in `ui/src/__tests__/setup.ts` so the race can't return undetected.

## Origin

Captured during feat_study_clone_from_previous Story 2.1 implementation
(branch `feature/study-clone-from-previous`). Running
`pnpm exec vitest run src/__tests__/components/common/data-table-col-vis-density.test.tsx`
in the worktree at `/private/tmp/relyloop-study-clone-from-previous`
surfaces 3 pre-existing failures in that file:

- `mounts with a pre-existing localStorage hidden entry — column starts hidden` (line 162)
- `tampered localStorage cannot hide a column with hideable: false` (line 172)
- `density toggle persists to localStorage and hydrates on mount` (line 201)

All three fail with:

```
TypeError: Cannot read properties of undefined (reading 'setItem')
 ❯ src/__tests__/components/common/data-table-col-vis-density.test.tsx:163:25
    163|     window.localStorage.setItem(
       |                         ^
```

(or `getItem` at line 204 for the density toggle test).

Verified pre-existing on `origin/main` via `git stash push -u` + re-run.
Neither the test file nor the `DataTable` component is on the branch's
delta (`git log --oneline origin/main..HEAD -- <file>` is empty).

## Problem

The first integration test in the file
(`toggling a column off via the menu removes its cells and persists to localStorage`,
line 148) accesses `window.localStorage` successfully. By the time the
3rd–5th tests run, `window.localStorage` is `undefined`. The
`beforeEach`/`afterEach` hooks at the top of the describe block already
wrap `localStorage.clear()` in `try { … } catch { /* ignore */ }`, which
swallows the symptom in cleanup but does NOT prevent the per-test
`setItem`/`getItem` calls from throwing.

This is the same class of bug as
[`bug_markdown_doc_localstorage_undefined_jsdom`](../bug_markdown_doc_localstorage_undefined_jsdom/idea.md)
— that one surfaces in a different test file
(`ui/src/__tests__/components/guides/markdown-doc.test.tsx`) with the
same root cause shape (jsdom `window.localStorage` going undefined
between tests).

## Why deferred

Out of scope for feat_study_clone_from_previous Story 2.1 — the failures
are in DataTable test infrastructure unrelated to the study-clone surface.
Verified that the Story 2.1 tests
(`prefill-from-study.test.ts` + `glossary.test.ts`) all pass in isolation
(`32 / 32`). Fix is small in scope but requires test-isolation
investigation (why does `window.localStorage` become undefined mid-suite?)
that is its own cross-cutting effort — better tackled together with the
sibling `bug_markdown_doc_localstorage_undefined_jsdom` as one infra-test
cleanup PR.

## Proposed fix

Either (preferred, fixes the root cause):

1. **Stub `localStorage` deterministically in `ui/src/__tests__/setup.ts`**
   so it survives across the entire test suite, not whatever default
   jsdom provides. Use `vi.stubGlobal('localStorage', { … })` in a
   `beforeAll` hook with the storage object recreated per-test.

Or (mitigation, doesn't fix the root cause):

2. **Guard every `window.localStorage` access** in the affected tests
   the same way the cleanup is guarded
   (`if (typeof window !== 'undefined' && window.localStorage)`). This
   matches the proposed fix in
   [`bug_markdown_doc_localstorage_undefined_jsdom`](../bug_markdown_doc_localstorage_undefined_jsdom/idea.md)
   but doesn't address why localStorage disappears.

Option 1 fixes both bug folders in one stroke and prevents future
test files from re-introducing the same failure mode.

## Suspected downstream effect

During the Story 2.1 sweep, `src/__tests__/app/studies/[id]/page.test.tsx`
also surfaced a 5-second `Test timed out in 5000ms` failure
(`renders header, trials table, and digest panel for a completed study`)
when run as part of the full suite — but **passes cleanly in isolation**
(`pnpm exec vitest run src/__tests__/app/studies/[id]/page.test.tsx`
reports `PASS (2) FAIL (0)`). This is most likely cross-test global-state
pollution caused by the same failing data-table tests above (the
localStorage `setItem` throws may leave React / MSW in an inconsistent
state for subsequent tests in the same vitest pool). Fixing the
localStorage root cause should resolve this cascade — verify after the
fix lands.

## Scope signals

- Frontend test-only change
- No production code modified
- Cross-cuts with [`bug_markdown_doc_localstorage_undefined_jsdom`](../bug_markdown_doc_localstorage_undefined_jsdom/idea.md) — fix them together
- Investigate vitest jsdom isolation defaults; consider `vitest --pool=threads`
  vs `--pool=forks` interaction with jsdom storage globals
