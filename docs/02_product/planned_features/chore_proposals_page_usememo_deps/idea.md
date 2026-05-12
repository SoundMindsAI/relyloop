# Idea — clean up `rows` useMemo dependency warning in /proposals page

**Date:** 2026-05-12
**Status:** Idea — deferred from `feat_proposals_ui` tangential sweep
**Origin:** `feat_proposals_ui` Story 2.1 (`ui/src/app/proposals/page.tsx`). Surfaced by ESLint after Story 2.1 landed; flagged again during the post-implementation tangential sweep (2026-05-12).

---

## Problem

`pnpm lint` emits one new warning on the proposals list page:

```
ui/src/app/proposals/page.tsx
  79:9  warning  The 'rows' logical expression could make the dependencies of useMemo Hook (at line 87)
                 change on every render. Move it inside the useMemo callback. Alternatively, wrap the
                 initialization of 'rows' in its own useMemo() Hook  react-hooks/exhaustive-deps
```

Lines 79–88 are:

```tsx
const rows = query.data?.data ?? [];
const visibleRows = useMemo(
  () =>
    rows.filter((r) => {
      if (sourceFilter === 'all') return true;
      if (sourceFilter === 'study') return r.study_id != null;
      return r.study_id == null;
    }),
  [rows, sourceFilter],
);
```

The `rows` reference changes identity on every render when `query.data` is undefined (the `?? []` creates a fresh array literal), defeating the useMemo's memoization. The behavior is correct (the `.filter()` produces the same elements), but the memoization is wasted CPU.

## Why deferred

- Only a warning, not an error.
- The wasted CPU is negligible — `.filter()` over ≤200 proposals per page is sub-millisecond.
- Fixing it touches a critical file (`/proposals/page.tsx`) and is better bundled with future polish work to avoid a one-line PR.

## Proposed fix

Two equivalent options:

**Option A** — Move the `rows` resolution inside the useMemo callback:

```tsx
const visibleRows = useMemo(() => {
  const rows = query.data?.data ?? [];
  return rows.filter(...);
}, [query.data, sourceFilter]);
```

**Option B** — Wrap the `rows` resolution in its own useMemo:

```tsx
const rows = useMemo(() => query.data?.data ?? [], [query.data]);
```

Option A is one less hook call and reads more naturally.

## Scope signals

- **Frontend impact:** 5 lines in `ui/src/app/proposals/page.tsx`.
- **Backend impact:** none.
- **Tests:** existing tests cover the visibleRows behavior — no test changes needed.
- **Migration:** none.

## Dependencies

- `feat_proposals_ui` (this folder's parent) must be merged so the file exists.

## Out of scope

- The broader pre-existing `react-hooks/incompatible-library` warnings in `feat_studies_ui` files (fork-template-modal.tsx, etc.) — those are a separate React-Hook-Form-watch issue and not introduced by this work.
