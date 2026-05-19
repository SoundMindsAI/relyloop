# DataTable primitive — review-cycle follow-ups

**Date:** 2026-05-16
**Status:** Partial — items 1, 2, 4, 6 shipped in PR #132 (squash commit `ee4c8d4`) 2026-05-17; item 3 closed 2026-05-19 (won't fix — flat-prop API locked as canonical, plan addendum required). Item 5 is the only residual implementation work: 1 primitive + (optionally) per-wrapper touch-ups.
**Origin:** [`feat_data_table_primitive`](../../../00_overview/implemented_features/2026_05_16_feat_data_table_primitive/) review cycles. Specific cycle/finding references inline below.
**Depends on:** `feat_data_table_primitive` (merged as PR #126).

## Problem

`feat_data_table_primitive` shipped with six known non-regression follow-up items captured only in chat transcripts. None block the PR but each is a real improvement that would otherwise evaporate when the session ends.

## Proposed capabilities

### 1. Factor the `searchParams subscriber` test mock pattern ✅ DONE 2026-05-17

**Origin:** session observation during test writing.

**Resolution:** Factored into `ui/src/__tests__/helpers/data-table-url-mock.ts` exporting `makeNextNavigationMock()` + `resetDataTableUrlMock()` + `getDataTableUrlMockState()` + `setMockedSearch()`. Three test files refactored to use the helper via `vi.mock('next/navigation', async () => { const mod = await import('../../helpers/data-table-url-mock'); return mod.makeNextNavigationMock(); })`. The async factory pattern sidesteps Vitest's `vi.mock` hoist trap (factory references its own-file imports). Net -85 LOC duplicated boilerplate across the three test files.

Four test files duplicate the same ~25-line `searchParamsSubscribers` + `applyUrl` mock setup that propagates URL changes through React state for `useDataTableUrlState`:

- `ui/src/__tests__/app/proposals/page.test.tsx`
- `ui/src/__tests__/app/judgments/[id]/page.test.tsx`
- `ui/src/__tests__/components/query-sets/queries-table.test.tsx`
- (and a partial in `ui/src/__tests__/app/studies/[id]/page.test.tsx`)

Factor into `ui/src/__tests__/helpers/data-table-url-mock.ts` exporting `setupDataTableUrlMock()` that returns `{ setSearch, getLastReplace, getLastPush }`. Next consumer that adds a DataTable URL-state test pulls the helper instead of duplicating.

> *(The shipped helper exposes a `vi.mock`-friendly API instead — `makeNextNavigationMock` / `resetDataTableUrlMock` / `getDataTableUrlMockState` / `setMockedSearch` — see Resolution above. The `setupDataTableUrlMock` text here is the original sketch; trust the Resolution paragraph for the canonical API.)*

### 2. `useLocalStorageSet` return shape ✅ DONE 2026-05-17

**Origin:** Epic 2 GPT-5.5 cycle 1 finding #14 (Low, deferred).

Plan Story 2.10 specifies `useLocalStorageSet` returns `{ value: string[], add(id), remove(id), toggle(id) }`. The implementation returns a `Set<string>` plus `clear()` + `has()` helpers. Works for current consumers but diverges from the documented API.

**Resolution:** Locked the shipped Set-based shape as canonical. The plan's `string[]` proposal was an early sketch — the actual consumer (`<DataTable>` at `ui/src/components/common/data-table.tsx`) uses `.has(c.id)` + `.toggle(id)`, which are Set-shaped operations. Set provides O(1) membership; array would force `.includes()` (O(n)). Updated the hook's docstring at `ui/src/hooks/use-local-storage-set.ts` to lock in the contract and reference this idea. No code change.

### 3. `DataTableProps` URL state aggregate prop — ✅ CLOSED 2026-05-19 (won't fix — doc the chosen shape)

**Origin:** Epic 2 GPT-5.5 cycle 1 finding #1 (High, deferred).

**Resolution:** Locked the shipped flat-prop API as canonical. The implemented plan's Story 2.6 key-interface block sketched `urlState: DataTableUrlState` + a `setSort`/`setFilter`/`setQ`/`setCursor`/`setPageSize` setter bag, but the build-out in stories 2.2-2.5 produced 10 flat optional props on [`DataTableProps`](../../../../ui/src/components/common/types.ts) (`sort?`, `onSortChange?`, `filters?`, `onFilterChange?`, `q?`, `onQChange?`, `cursor?`, `onCursorChange?`, `onPageSizeChange?`, `sortCodec?`). Rationale for closing:

- The plan in `implemented_features/2026_05_16_feat_data_table_primitive/` is a historical record; the shipped code is the live contract that the 8 thin-wrapper consumers depend on.
- The flat-prop API is idiomatic React + aligns with shadcn primitives (consumer passes value + onChange pairs directly).
- All 8 consumers (`clusters/clusters-table.tsx`, `judgments/judgments-table.tsx`, `proposals/proposals-table.tsx`, `query-sets/queries-table.tsx`, `query-sets/query-sets-table.tsx`, `studies/studies-table.tsx`, `studies/trials-table.tsx`, `templates/templates-table.tsx`) work cleanly with the shipped shape.
- Refactor cost (~250 LOC across 9 files) doesn't justify the marginal API-aesthetics gain.

Companion patch to the historical plan: [`implemented_features/2026_05_16_feat_data_table_primitive/implementation_plan.md` Story 2.6 key-interface block](../../../00_overview/implemented_features/2026_05_16_feat_data_table_primitive/implementation_plan.md) gains a "Shipped contract" addendum noting the divergence from the sketched aggregate-prop shape and pointing back to this idea for the rationale.

### 4. `?limit=` coercion to `pageSizeOptions` allowlist ✅ DONE 2026-05-17

**Origin:** Epic 2 GPT-5.5 cycle 2 finding #13 (Medium, deferred).

`useDataTableUrlState` currently accepts any positive integer for `?limit=` (e.g., `?limit=99` becomes `pageSize=99`). The hook accepts `pageSizeOptions` in its config but doesn't use it for hydration validation. Tightening would coerce out-of-allowlist values to `defaultPageSize`.

**Resolution:** Added pageSize coercion at hook hydration: when `options.pageSizeOptions` is provided, out-of-allowlist `?limit=` values fall back to `defaultPageSize`. Backward-compatible — when `pageSizeOptions` is omitted (current consumer pattern), any positive integer still passes. 4 new test cases at `ui/src/__tests__/hooks/use-data-table-url-state.test.tsx`.

### 5. TanStack `state.columnVisibility` wire-up

**Origin:** Epic 2 GPT-5.5 cycle 3 finding #3 (Low, deferred).

Current implementation pre-filters `columns` before passing to `useReactTable`. The TanStack-idiomatic approach is to pass the full column array and use `state.columnVisibility: Record<id, boolean>` to control visibility. Functional today; refactor would compose better with future column-state features (column ordering, pinning, resizing).

### 6. URL-state Zod validation in `useDataTableUrlState` ✅ DONE 2026-05-17

**Origin:** Epic 2 GPT-5.5 cycle 3 finding #1 (Medium, deferred).

Direct URLs like `?status=invented` or `?sort=garbage:asc` currently pass through `useDataTableUrlState` unchanged and fail at the backend with a 422. Defense-in-depth would validate against `column.filter.wireValues` (enum filters) and `column.sortable` + `column.sortDirections` (sort) at the hook level, dropping invalid params and optionally calling `replace()` to clean the URL.

**Resolution:** Centralized validation in `useDataTableUrlState` for enum-filter columns and sort tokens. Enum filters drop values outside `column.filter.wireValues`. Sort tokens drop tokens whose column isn't sortable OR whose direction isn't in `column.sortDirections`. fk-select filters pass through (their option IDs load async, so can't validate at hook time). Did NOT call `replace()` to clean the URL — dropping silently avoids the "flash of empty state" UX surprise, matching the page-level pattern in `/proposals/page.tsx`. 7 new test cases.

## Scope signals

- **Backend:** none for items 1, 2, 3, 4, 5; minor for item 6 (depends on whether validation surfaces as a separate primitive or stays in the hook).
- **Frontend:** items 1 (test only), 2 (1 hook + 2 call sites), 3 (8 thin wrappers), 4 (1 hook), 5 (1 primitive + 8 thin wrappers), 6 (1 hook + tests).
- **Migration:** none.
- **Config:** none.
- **Audit events:** none — all reads.

## Why deferred

Each item was reviewed and adjudicated "non-regression follow-up" during the parent PR's review cycles. None block correctness; each improves consistency, encapsulation, or defense-in-depth. Bundling into one chore folder so they ship together (or get dropped together) when picked up.

## Open questions for /spec-gen

- **Q1 — Item 3 scope.** ✅ **Locked 2026-05-19: close item 3 (won't fix), lock the flat-prop API as canonical, add a "Shipped contract" addendum to the historical implementation plan's Story 2.6 key-interface block.** See item 3 above for the full rationale.
- **Q2 — Item 5 cleanup scope: just the primitive, or also the wrapper-level prop changes?** Migrating to TanStack `state.columnVisibility` is straightforward in [`data-table.tsx:259-267`](../../../../ui/src/components/common/data-table.tsx) (pre-filter → full columns + `state.columnVisibility` derived from the same `useLocalStorageSet`). Recommended default: **primitive-only.** The 8 thin wrappers don't touch column visibility today; the localStorage key + the `useLocalStorageSet` integration stay unchanged. Refactor is contained to the primitive's `useReactTable()` call and the `visibleColumns`/`columns` props passed downstream.

## Folder-name note

With Q1 locked (item 3 closed), the residual scope is item 5 only (TanStack `state.columnVisibility` migration) plus the historical-plan addendum. Current folder name `chore_data_table_primitive_followups` is now broader than the residual work. Candidate rename: **`chore_data_table_columnvisibility_tanstack`** (4 tokens, intent-clear). Rename requires explicit user confirmation per the preflight skill's folder-rename gate — not applied automatically.

## Relationship to other work

- **Parent:** `feat_data_table_primitive` (PR #126).
- **Adjacent deferred:** `feat_fts_rank_ordering_mvp2` (rank-ordered FTS) — different concern (backend ordering), no overlap.
- **Sibling check (clean):** `chore_form_dropdown_primitive` (shipped, PR #136), `chore_detail_page_shell_primitive` (idea-stage, PR #147) — both touch different surfaces. `chore_ci_prettier_check` is the only sibling that *could* affect a future PR for this chore (catches `prettier` drift in changed files), but doesn't conflict.
