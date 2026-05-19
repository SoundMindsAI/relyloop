# Extract the shadcn `<Select>` vitest mock into a shared helper

**Date:** 2026-05-18
**Status:** Idea — captured during `chore_form_dropdown_primitive` execution (PR pending).
**Origin:** During Story 2.x of `chore_form_dropdown_primitive`, three modal test files ended up with the same ~50-LOC `vi.mock('@/components/ui/select', async () => { ... })` block:

- [`ui/src/__tests__/components/studies/create-study-modal.test.tsx`](../../../../ui/src/__tests__/components/studies/create-study-modal.test.tsx) (lines 15-60, pre-existed before the migration)
- [`ui/src/__tests__/components/query-sets/create-query-set-modal.test.tsx`](../../../../ui/src/__tests__/components/query-sets/create-query-set-modal.test.tsx) (lines 18-76, added by Story 2.1)
- [`ui/src/__tests__/components/clusters/register-cluster-modal.test.tsx`](../../../../ui/src/__tests__/components/clusters/register-cluster-modal.test.tsx) (lines 15-73, added by Story 2.3)

The mock replaces the Radix-based shadcn `<Select>` family with a native `<select>` shim because the real Radix primitives crash inside jsdom + Dialog (the testing-library `patchedFocus` shim recurses infinitely via Radix's internal focus-trap). The Story 2.1/2.3 mocks extend the original with `data-testid` forwarding.

**Depends on:** None.

## Problem

A factor-and-share refactor was attempted during `chore_form_dropdown_primitive` post-implementation. I extracted the mock to `ui/src/__tests__/helpers/shadcn-select-mock.tsx` exporting `mockShadcnSelect: () => Promise<...>` and rewrote the three modal tests to `import { mockShadcnSelect } from '../../helpers/shadcn-select-mock'; vi.mock('@/components/ui/select', mockShadcnSelect);`. **All three test files failed at import** with vitest's classic `vi.mock` hoisting issue: `vi.mock()` calls are hoisted to the top of the file before all imports, so the `mockShadcnSelect` identifier is unbound at call time.

I reverted the refactor and left the duplication in place.

## Proposed capabilities

Factor the mock into a shared helper using **`vi.hoisted()`** so it survives vitest's hoisting machinery:

```ts
// At top of a *.test.tsx file (no separate import needed at module scope):
const { mockShadcnSelect } = vi.hoisted(async () => {
  const { mockShadcnSelect } = await import('../../helpers/shadcn-select-mock');
  return { mockShadcnSelect };
});
vi.mock('@/components/ui/select', mockShadcnSelect);
```

The helper module exports the factory as before:

```ts
// ui/src/__tests__/helpers/shadcn-select-mock.tsx
export const mockShadcnSelect = async () => { /* the 50-LOC factory */ };
```

Three call sites change from a 50-LOC inline `vi.mock` block to a 4-LOC `vi.hoisted` + `vi.mock` pair. Net reduction: ~140 LOC.

Alternative if `vi.hoisted` proves too brittle: leave the duplication and revisit if a 4th consumer lands. The mock is small enough that copy-paste is acceptable — the pattern is documented in [`docs/01_architecture/ui-architecture.md` §"Form dropdown primitive"](../../../01_architecture/ui-architecture.md) "Modal-level testing" so future contributors find it.

## Scope signals

- **Backend:** none.
- **Frontend:**
  - 1 new helper file at `ui/src/__tests__/helpers/shadcn-select-mock.tsx` (~70 LOC).
  - 3 modal test files lose ~50 LOC each, gain ~4 LOC each. Net ~140 LOC deletion.
- **Migration:** none.
- **Config:** none.
- **Audit events:** none.
- **Tests:** the helper itself has no co-located test (it's a test helper); validation is "the three test files still pass after refactor."
- **Docs:** ui-architecture.md's "Modal-level testing" paragraph already cites the helper concept; add a one-line update pointing at the actual helper file path when it lands.

## Why deferred

`vi.hoisted` is the canonical vitest API for this exact problem, but the wrapper closure adds a layer of indirection that's not immediately obvious to new contributors. The duplication today is bearable (3 sites, 50 LOC each = 150 LOC of identical scaffolding). The marginal value of factoring drops once the test-mock pattern is in CLAUDE.md or ui-architecture.md as documented prior art — which it now is.

This idea is worth picking up when:
- A 4th consumer of the shadcn `<Select>` mock is needed (e.g., a new form modal at MVP4 tenant-picker or similar).
- A contributor with vitest hoisting expertise has 15 minutes.
- The `vi.hoisted` API surface stabilizes further (it's been in vitest since v0.31 but the async-factory variant is less battle-tested).

## Recommended pipeline path

`/impl-execute --ad-hoc` — single small commit on a feature branch, ~30 minutes of work, no spec needed. The change is mechanical and well-bounded.
