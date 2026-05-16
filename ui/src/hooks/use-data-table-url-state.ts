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

import { useRouter, useSearchParams } from 'next/navigation';
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
  const { defaultPageSize = DEFAULT_PAGE_SIZE } = options;

  // Filter-column names — the hook only parses URL params whose name appears
  // in this set; everything else (route-level params) is preserved untouched.
  const filterColumnIds = useMemo(
    () => new Set(columns.filter((c) => c.filter).map((c) => c.id)),
    [columns],
  );

  const filters = useMemo(() => {
    const out: Record<string, string> = {};
    filterColumnIds.forEach((id) => {
      const v = searchParams.get(id);
      if (v) out[id] = v;
    });
    return out;
  }, [filterColumnIds, searchParams]);

  const sort = searchParams.get('sort');
  // Normalize empty or whitespace `?q=` to null — `?q=` and `?q=   ` are
  // not meaningful matchers and must not flip `anyMatcherActive` true.
  const qRaw = searchParams.get('q');
  const q = qRaw && qRaw.trim() ? qRaw : null;
  const cursor = searchParams.get('cursor');
  const limitRaw = searchParams.get('limit');
  const pageSize = limitRaw ? Number(limitRaw) || defaultPageSize : defaultPageSize;

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
      const url = qs ? `?${qs}` : window.location.pathname;
      if (strategy === 'push') {
        router.push(url);
      } else {
        router.replace(url);
      }
    },
    [router, searchParams],
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
