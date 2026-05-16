# DataTable primitive — review-cycle follow-ups

**Date:** 2026-05-16
**Status:** Idea — six discrete follow-ups deferred from `feat_data_table_primitive` GPT-5.5 review cycles (Epic 2 cycles 1/2/3 + Epic 3 cycle 1) and from Step 2.5 tangential-observations sweep. Each was correctly classified "defer as non-regression follow-up" at the time; capturing them now per the CLAUDE.md tangential-discoveries rule so they don't evaporate.
**Origin:** [`feat_data_table_primitive/implementation_plan.md`](../feat_data_table_primitive/implementation_plan.md) review cycles. Specific cycle/finding references inline below.
**Depends on:** `feat_data_table_primitive` (PR open on `feat/data-table-primitive`).

## Problem

`feat_data_table_primitive` shipped with six known non-regression follow-up items captured only in chat transcripts. None block the PR but each is a real improvement that would otherwise evaporate when the session ends.

## Proposed capabilities

### 1. Factor the `searchParams subscriber` test mock pattern

**Origin:** session observation during test writing.

Four test files duplicate the same ~25-line `searchParamsSubscribers` + `applyUrl` mock setup that propagates URL changes through React state for `useDataTableUrlState`:

- `ui/src/__tests__/app/proposals/page.test.tsx`
- `ui/src/__tests__/app/judgments/[id]/page.test.tsx`
- `ui/src/__tests__/components/query-sets/queries-table.test.tsx`
- (and a partial in `ui/src/__tests__/app/studies/[id]/page.test.tsx`)

Factor into `ui/src/__tests__/helpers/data-table-url-mock.ts` exporting `setupDataTableUrlMock()` that returns `{ setSearch, getLastReplace, getLastPush }`. Next consumer that adds a DataTable URL-state test pulls the helper instead of duplicating.

### 2. `useLocalStorageSet` return shape

**Origin:** Epic 2 GPT-5.5 cycle 1 finding #14 (Low, deferred).

Plan Story 2.10 specifies `useLocalStorageSet` returns `{ value: string[], add(id), remove(id), toggle(id) }`. The implementation returns a `Set<string>` plus `clear()` + `has()` helpers. Works for current consumers but diverges from the documented API.

Decision needed: update the plan to match the impl, or refactor the impl to return `{value: string[], ...}` and adapt the 2 call sites.

### 3. `DataTableProps` URL state aggregate prop

**Origin:** Epic 2 GPT-5.5 cycle 1 finding #1 (High, deferred).

Plan Story 2.6 key-interface block declares `DataTableProps` gaining required `urlState: DataTableUrlState` + `setSort`/`setFilter`/`setQ`/`setCursor`/`setPageSize` props after the URL hook lifts. The implementation kept the flat optional props (`sort?`, `onSortChange?`, etc.) from the 2.2-2.5 build-out — works as a controlled contract but doesn't match the plan's compact shape.

Refactor would touch every Epic 3 consumer (8 thin wrappers). The flat-prop API is also slightly more idiomatic React; the question is whether the plan should be updated to reflect the chosen design or the code should be updated to reflect the plan.

### 4. `?limit=` coercion to `pageSizeOptions` allowlist

**Origin:** Epic 2 GPT-5.5 cycle 2 finding #13 (Medium, deferred).

`useDataTableUrlState` currently accepts any positive integer for `?limit=` (e.g., `?limit=99` becomes `pageSize=99`). The hook accepts `pageSizeOptions` in its config but doesn't use it for hydration validation. Tightening would coerce out-of-allowlist values to `defaultPageSize`.

Low-priority — the backend caps `?limit=200` per `api-conventions.md` so the worst case is a 99-row page render rather than data loss.

### 5. TanStack `state.columnVisibility` wire-up

**Origin:** Epic 2 GPT-5.5 cycle 3 finding #3 (Low, deferred).

Current implementation pre-filters `columns` before passing to `useReactTable`. The TanStack-idiomatic approach is to pass the full column array and use `state.columnVisibility: Record<id, boolean>` to control visibility. Functional today; refactor would compose better with future column-state features (column ordering, pinning, resizing).

### 6. URL-state Zod validation in `useDataTableUrlState`

**Origin:** Epic 2 GPT-5.5 cycle 3 finding #1 (Medium, deferred).

Direct URLs like `?status=invented` or `?sort=garbage:asc` currently pass through `useDataTableUrlState` unchanged and fail at the backend with a 422. Defense-in-depth would validate against `column.filter.wireValues` (enum filters) and `column.sortable` + `column.sortDirections` (sort) at the hook level, dropping invalid params and optionally calling `replace()` to clean the URL.

Most surfaces already narrow this at the page level (e.g., `/proposals/page.tsx` checks `PROPOSAL_STATUS_VALUES.includes()` before calling the API). Centralizing in the hook would make the discipline consistent across all 8 consumers.

## Scope signals

- **Backend:** none for items 1, 2, 3, 4, 5; minor for item 6 (depends on whether validation surfaces as a separate primitive or stays in the hook).
- **Frontend:** items 1 (test only), 2 (1 hook + 2 call sites), 3 (8 thin wrappers), 4 (1 hook), 5 (1 primitive + 8 thin wrappers), 6 (1 hook + tests).
- **Migration:** none.
- **Config:** none.
- **Audit events:** none — all reads.

## Why deferred

Each item was reviewed and adjudicated "non-regression follow-up" during the parent PR's review cycles. None block correctness; each improves consistency, encapsulation, or defense-in-depth. Bundling into one chore folder so they ship together (or get dropped together) when picked up.

## Relationship to other work

- **Parent:** `feat_data_table_primitive`.
- **Adjacent deferred:** `feat_fts_rank_ordering_mvp2` (rank-ordered FTS) — different concern (backend ordering), no overlap.
