'use client';

/**
 * `useDataTableUrlState` — page-level URL-state hook for `<DataTable>`
 * (feat_data_table_primitive Story 2.6 / FR-8).
 *
 * Lives at the **consumer** (the page that hosts the DataTable) so the
 * consumer's TanStack Query hook can read URL state and refetch on change.
 * DataTable then becomes a controlled component receiving `urlState` +
 * setters as props.
 *
 * History strategy (per FR-8):
 * - **Cursor-page navigation** (`setCursor` from Next / Prev) uses
 *   `router.push()` so the browser's Back button steps through pages.
 * - **Filter / sort / search changes** use `router.replace()` so quick UI
 *   tweaks don't pollute the history stack. Each of those changes also
 *   clears `?cursor=` (page resets to first).
 * - **`clearAllMatchers`** clears every filter param + `?q=` while
 *   preserving sort + pageSize. Wired to the FR-9 "no-rows-match" empty
 *   state's "Clear filters" button.
 *
 * Page-size is part of the URL state (`?limit=`) so the consumer's query
 * hook can pass `limit: urlState.pageSize` through.
 */

import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useMemo } from 'react';

import type { DataTableColumnDef } from '@/components/common/types';

export interface DataTableUrlState {
  sort: string | null;
  filters: Record<string, string>;
  q: string | null;
  cursor: string | null;
  pageSize: number;
}

export interface DataTableUrlStateApi extends DataTableUrlState {
  setSort: (sort: string | null) => void;
  setFilter: (column: string, value: string | null) => void;
  setQ: (q: string | null) => void;
  setCursor: (cursor: string | null) => void;
  setPageSize: (pageSize: number) => void;
  clearCursor: () => void;
  /** Clears all filter chips + `?q=`; preserves sort + pageSize. */
  clearAllMatchers: () => void;
  /** True when ≥1 column filter OR `?q=` is active. */
  anyMatcherActive: boolean;
}

export interface UseDataTableUrlStateOptions {
  defaultPageSize?: number;
  pageSizeOptions?: readonly number[];
}

const DEFAULT_PAGE_SIZE = 50;

export function useDataTableUrlState<T extends { id: string }>(
  _tableId: string,
  columns: readonly DataTableColumnDef<T>[],
  options: UseDataTableUrlStateOptions = {},
): DataTableUrlStateApi {
  const router = useRouter();
  const searchParams = useSearchParams();
  // `usePathname` is the SSR-safe idiomatic way to read the current path in
  // the App Router. Used below in `navigate` instead of
  // `window.location.pathname`, which is undefined during the initial
  // server render.
  const pathname = usePathname();
  const { defaultPageSize = DEFAULT_PAGE_SIZE, pageSizeOptions } = options;

  // Filter-column names — the hook only parses URL params whose name appears
  // in this set; everything else (route-level params) is preserved untouched.
  const filterColumnIds = useMemo(
    () => new Set(columns.filter((c) => c.filter).map((c) => c.id)),
    [columns],
  );

  // Per-column wireValues allowlist for enum filters. fk-select filters
  // can't be validated at hook-time (their option IDs load async) so they
  // pass through unchanged. Per `chore_data_table_primitive_followups`
  // item 6 — defense-in-depth: a direct URL with `?status=invented`
  // hydrates as an empty filter instead of being sent to the backend
  // and surfacing as 422 VALIDATION_ERROR.
  const enumWireValueSets = useMemo(() => {
    const out: Record<string, Set<string>> = {};
    columns.forEach((c) => {
      if (c.filter?.kind === 'enum') {
        out[c.id] = new Set(c.filter.wireValues);
      }
    });
    return out;
  }, [columns]);

  // Sort-token allowlist: `<col>:<dir>` is only valid when `col` is the
  // `sortKey` (or `id`) of a sortable column AND `dir` is in that column's
  // `sortDirections` (defaults to both `asc` + `desc`). Per `chore_data_table_primitive_followups`
  // item 6 — direct URLs like `?sort=garbage:asc` or `?sort=name:upward`
  // hydrate as no sort instead of flowing to the backend (and either
  // 422-ing or silently no-op'ing).
  const sortKeyDirections = useMemo(() => {
    const out: Record<string, Set<'asc' | 'desc'>> = {};
    columns.forEach((c) => {
      if (c.sortable) {
        const key = c.sortKey ?? c.id;
        const dirs = c.sortDirections ?? (['asc', 'desc'] as const);
        out[key] = new Set(dirs);
      }
    });
    return out;
  }, [columns]);

  const filters = useMemo(() => {
    const out: Record<string, string> = {};
    filterColumnIds.forEach((id) => {
      const v = searchParams.get(id);
      if (!v) return;
      const allowed = enumWireValueSets[id];
      // Enum filters: drop values not in the wireValues allowlist.
      // fk-select filters: pass through (validated at the backend boundary).
      if (allowed && !allowed.has(v)) return;
      out[id] = v;
    });
    return out;
  }, [filterColumnIds, searchParams, enumWireValueSets]);

  // Sort validation. Splits `<col>:<dir>`, checks col is a known sortable
  // column, dir is in that column's allowed cycle. Returns null on any
  // structural mismatch so the consumer hook passes no `?sort=` to the
  // backend (rather than a malformed value that would 422).
  const sortRaw = searchParams.get('sort');
  const sort = useMemo(() => {
    if (!sortRaw) return null;
    const [col, dir] = sortRaw.split(':');
    if (!col) return null;
    const allowedDirs = sortKeyDirections[col];
    if (!allowedDirs) return null;
    // `dir` is undefined (`?sort=name` → no colon) or `'asc'` / `'desc'`.
    // Mirror the backend `parse_sort` helper's contract
    // (`backend/app/db/repo/_sort.py:50-56`): anything other than the
    // literal `"desc"` resolves to `"asc"`. We do NOT synthesize a
    // direction from the column's `sortDirections` when the URL omits
    // it — a desc-only column with `?sort=col` (no direction) resolves
    // to `col:asc`, which the column's allowlist rejects, and the
    // whole sort falls through to `null`. This is intentional: silently
    // producing `col:desc` for a `?sort=col` URL would be guessing what
    // the user meant and would surprise callers copy-pasting URLs.
    const resolved = dir === 'desc' ? 'desc' : 'asc';
    if (!allowedDirs.has(resolved)) return null;
    return `${col}:${resolved}`;
  }, [sortRaw, sortKeyDirections]);
  // Normalize empty or whitespace `?q=` to null — `?q=` and `?q=   ` are
  // not meaningful matchers and must not flip `anyMatcherActive` true.
  const qRaw = searchParams.get('q');
  const q = qRaw && qRaw.trim() ? qRaw : null;
  const cursor = searchParams.get('cursor');
  // Page-size validation. When `pageSizeOptions` is provided, coerce
  // out-of-allowlist `?limit=` values to `defaultPageSize`. Per
  // `chore_data_table_primitive_followups` item 4 — guards against
  // ad-hoc `?limit=99` URLs that produce inconsistent page sizes
  // across the surface; backend caps at 200 (api-conventions §Pagination)
  // but the frontend allowlist is typically much tighter.
  const limitRaw = searchParams.get('limit');
  const pageSize = useMemo(() => {
    if (!limitRaw) return defaultPageSize;
    // `parseInt` (not `Number`) enforces the integer contract — `?limit=10.5`
    // becomes `10`, and the result is then checked against `pageSizeOptions`
    // so fractional values can't reach `?limit=` API calls.
    const parsed = parseInt(limitRaw, 10);
    if (!parsed || parsed <= 0) return defaultPageSize;
    if (pageSizeOptions && !pageSizeOptions.includes(parsed)) return defaultPageSize;
    return parsed;
  }, [limitRaw, defaultPageSize, pageSizeOptions]);

  const anyMatcherActive = Object.keys(filters).length > 0 || q !== null;

  // Build the new URL given a delta + a strategy (push vs replace).
  const navigate = useCallback(
    (delta: Record<string, string | null>, strategy: 'push' | 'replace') => {
      const next = new URLSearchParams(searchParams.toString());
      for (const [key, value] of Object.entries(delta)) {
        if (value === null || value === '') {
          next.delete(key);
        } else {
          next.set(key, value);
        }
      }
      const qs = next.toString();
      const url = qs ? `?${qs}` : pathname;
      if (strategy === 'push') {
        router.push(url);
      } else {
        router.replace(url);
      }
    },
    [router, searchParams, pathname],
  );

  const setSort = useCallback(
    (value: string | null) => navigate({ sort: value, cursor: null }, 'replace'),
    [navigate],
  );

  const setFilter = useCallback(
    (column: string, value: string | null) =>
      navigate({ [column]: value, cursor: null }, 'replace'),
    [navigate],
  );

  const setQ = useCallback(
    (value: string | null) => navigate({ q: value, cursor: null }, 'replace'),
    [navigate],
  );

  const setCursor = useCallback(
    (value: string | null) => navigate({ cursor: value }, 'push'),
    [navigate],
  );

  const setPageSize = useCallback(
    (value: number) =>
      navigate(
        { limit: value === defaultPageSize ? null : String(value), cursor: null },
        'replace',
      ),
    [navigate, defaultPageSize],
  );

  const clearCursor = useCallback(() => navigate({ cursor: null }, 'replace'), [navigate]);

  const clearAllMatchers = useCallback(() => {
    const delta: Record<string, string | null> = { q: null, cursor: null };
    filterColumnIds.forEach((id) => {
      delta[id] = null;
    });
    navigate(delta, 'replace');
  }, [navigate, filterColumnIds]);

  return {
    sort,
    filters,
    q,
    cursor,
    pageSize,
    setSort,
    setFilter,
    setQ,
    setCursor,
    setPageSize,
    clearCursor,
    clearAllMatchers,
    anyMatcherActive,
  };
}
