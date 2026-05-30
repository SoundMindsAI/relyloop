// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * `useDataTableUrlState` hook tests (feat_data_table_primitive Story 2.6 / FR-8).
 *
 * Verifies the controlled URL-state contract:
 *   - Cursor changes use `router.push()` (so Back steps through pages).
 *   - Sort / filter / q / pageSize changes use `router.replace()` (no
 *     history pollution) AND clear `?cursor=`.
 *   - `clearAllMatchers()` clears every filter + q; preserves sort + pageSize.
 *   - `anyMatcherActive` reflects filter+q presence; ignores sort.
 *
 * `next/navigation` is mocked so the test doesn't need a real Next router.
 */

import { renderHook, act } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { DataTableColumnDef } from '@/components/common/types';
import { useDataTableUrlState } from '@/hooks/use-data-table-url-state';

interface MockRow {
  id: string;
}

const columns: DataTableColumnDef<MockRow>[] = [
  {
    id: 'status',
    header: 'Status',
    filter: { kind: 'enum', wireValues: ['queued', 'running', 'completed'], sourceOfTruth: 'test' },
  },
  {
    id: 'source',
    header: 'Source',
    filter: { kind: 'enum', wireValues: ['llm', 'human'], sourceOfTruth: 'test' },
  },
  // A sortable column used by the hydration test below — without one, the
  // chore_data_table_columnvisibility_tanstack item 6 sort-token validation
  // (added 2026-05-17) drops `?sort=name:asc` as "no such sortable column."
  { id: 'name', header: 'Name', sortable: true },
];

const pushMock = vi.fn();
const replaceMock = vi.fn();
let currentSearch = '';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: pushMock, replace: replaceMock }),
  useSearchParams: () => new URLSearchParams(currentSearch),
  usePathname: () => '/studies',
}));

beforeEach(() => {
  pushMock.mockReset();
  replaceMock.mockReset();
  currentSearch = '';
});

afterEach(() => {
  currentSearch = '';
});

describe('useDataTableUrlState — read', () => {
  it('hydrates from URL on mount', () => {
    currentSearch = 'status=completed&sort=name%3Aasc&q=test&cursor=opaque&limit=100';
    const { result } = renderHook(() => useDataTableUrlState('mock', columns));
    expect(result.current.sort).toBe('name:asc');
    expect(result.current.filters).toEqual({ status: 'completed' });
    expect(result.current.q).toBe('test');
    expect(result.current.cursor).toBe('opaque');
    expect(result.current.pageSize).toBe(100);
    expect(result.current.anyMatcherActive).toBe(true);
  });

  it('ignores URL params that do not belong to a filter column', () => {
    currentSearch = 'unrelated=foo&status=running';
    const { result } = renderHook(() => useDataTableUrlState('mock', columns));
    expect(result.current.filters).toEqual({ status: 'running' });
  });

  it('returns default pageSize when ?limit= is absent', () => {
    currentSearch = '';
    const { result } = renderHook(() =>
      useDataTableUrlState('mock', columns, { defaultPageSize: 25 }),
    );
    expect(result.current.pageSize).toBe(25);
  });
});

describe('useDataTableUrlState — write strategies (push vs replace)', () => {
  it('setSort uses replace + clears cursor', () => {
    currentSearch = 'cursor=oldcursor';
    const { result } = renderHook(() => useDataTableUrlState('mock', columns));
    act(() => result.current.setSort('name:asc'));
    expect(replaceMock).toHaveBeenCalledTimes(1);
    expect(pushMock).not.toHaveBeenCalled();
    const url = String(replaceMock.mock.calls[0]?.[0] ?? '');
    expect(url).toMatch(/sort=name%3Aasc/);
    expect(url).not.toMatch(/cursor=/);
  });

  it('setFilter uses replace + clears cursor', () => {
    currentSearch = 'cursor=oldcursor';
    const { result } = renderHook(() => useDataTableUrlState('mock', columns));
    act(() => result.current.setFilter('status', 'completed'));
    expect(replaceMock).toHaveBeenCalledTimes(1);
    expect(pushMock).not.toHaveBeenCalled();
    const url = String(replaceMock.mock.calls[0]?.[0] ?? '');
    expect(url).toMatch(/status=completed/);
    expect(url).not.toMatch(/cursor=/);
  });

  it('setQ uses replace + clears cursor', () => {
    currentSearch = 'cursor=oldcursor';
    const { result } = renderHook(() => useDataTableUrlState('mock', columns));
    act(() => result.current.setQ('product'));
    expect(replaceMock).toHaveBeenCalledTimes(1);
    expect(pushMock).not.toHaveBeenCalled();
    const url = String(replaceMock.mock.calls[0]?.[0] ?? '');
    expect(url).toMatch(/q=product/);
    expect(url).not.toMatch(/cursor=/);
  });

  it('setCursor uses push (so Back steps through pages)', () => {
    currentSearch = '';
    const { result } = renderHook(() => useDataTableUrlState('mock', columns));
    act(() => result.current.setCursor('newcursor'));
    expect(pushMock).toHaveBeenCalledTimes(1);
    expect(replaceMock).not.toHaveBeenCalled();
    const url = String(pushMock.mock.calls[0]?.[0] ?? '');
    expect(url).toMatch(/cursor=newcursor/);
  });

  it('clearAllMatchers clears every filter + q; preserves sort + pageSize', () => {
    currentSearch = 'status=completed&source=llm&q=foo&sort=name%3Aasc&limit=100';
    const { result } = renderHook(() => useDataTableUrlState('mock', columns));
    act(() => result.current.clearAllMatchers());
    expect(replaceMock).toHaveBeenCalledTimes(1);
    const newUrl = String(replaceMock.mock.calls[0]?.[0] ?? '');
    expect(newUrl).not.toMatch(/status=/);
    expect(newUrl).not.toMatch(/source=/);
    expect(newUrl).not.toMatch(/q=/);
    // sort + limit preserved
    expect(newUrl).toMatch(/sort=name%3Aasc/);
    expect(newUrl).toMatch(/limit=100/);
  });

  it('setPageSize drops limit when value equals defaultPageSize', () => {
    currentSearch = 'limit=200';
    const { result } = renderHook(() =>
      useDataTableUrlState('mock', columns, { defaultPageSize: 50 }),
    );
    act(() => result.current.setPageSize(50));
    const newUrl = String(replaceMock.mock.calls[0]?.[0] ?? '');
    expect(newUrl).not.toMatch(/limit=/);
  });
});

describe('useDataTableUrlState — anyMatcherActive', () => {
  it('returns false when no filter and no q are active', () => {
    currentSearch = 'sort=name%3Aasc';
    const { result } = renderHook(() => useDataTableUrlState('mock', columns));
    expect(result.current.anyMatcherActive).toBe(false);
  });

  it('returns true when a filter is active', () => {
    currentSearch = 'status=running';
    const { result } = renderHook(() => useDataTableUrlState('mock', columns));
    expect(result.current.anyMatcherActive).toBe(true);
  });

  it('returns true when q is active', () => {
    currentSearch = 'q=foo';
    const { result } = renderHook(() => useDataTableUrlState('mock', columns));
    expect(result.current.anyMatcherActive).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// chore_data_table_columnvisibility_tanstack item 6 — URL-state validation
// ---------------------------------------------------------------------------
describe('useDataTableUrlState — enum filter validation', () => {
  it('drops a filter value not in the column wireValues allowlist', () => {
    currentSearch = 'status=invented';
    const { result } = renderHook(() => useDataTableUrlState('mock', columns));
    expect(result.current.filters).toEqual({});
    expect(result.current.anyMatcherActive).toBe(false);
  });

  it('preserves a filter value that matches the wireValues allowlist', () => {
    currentSearch = 'status=running';
    const { result } = renderHook(() => useDataTableUrlState('mock', columns));
    expect(result.current.filters).toEqual({ status: 'running' });
  });

  it('drops only the invalid filter; leaves valid siblings intact', () => {
    currentSearch = 'status=invented&source=llm';
    const { result } = renderHook(() => useDataTableUrlState('mock', columns));
    expect(result.current.filters).toEqual({ source: 'llm' });
  });
});

const sortColumns: DataTableColumnDef<MockRow>[] = [
  { id: 'name', header: 'Name', sortable: true },
  { id: 'version', header: 'Version', sortable: true, sortDirections: ['asc'] },
];

describe('useDataTableUrlState — sort token validation', () => {
  it('drops a sort token whose column is not in the sortable allowlist', () => {
    currentSearch = 'sort=invented:asc';
    const { result } = renderHook(() => useDataTableUrlState('mock', sortColumns));
    expect(result.current.sort).toBeNull();
  });

  it('drops a sort token whose direction is not in the column sortDirections', () => {
    // version is asc-only; ?sort=version:desc must fall through to null.
    currentSearch = 'sort=version:desc';
    const { result } = renderHook(() => useDataTableUrlState('mock', sortColumns));
    expect(result.current.sort).toBeNull();
  });

  it('accepts a sort token within the column sortDirections', () => {
    currentSearch = 'sort=version:asc';
    const { result } = renderHook(() => useDataTableUrlState('mock', sortColumns));
    expect(result.current.sort).toBe('version:asc');
  });

  it('defaults to asc when ?sort=<col> is missing the direction half', () => {
    currentSearch = 'sort=name';
    const { result } = renderHook(() => useDataTableUrlState('mock', sortColumns));
    expect(result.current.sort).toBe('name:asc');
  });

  it('drops ?sort=<col> on a desc-only column (no synthesizing direction)', () => {
    // Regression for Gemini PR #132 finding: `?sort=version` (no direction)
    // resolves to `version:asc` via the backend-mirroring fallback. The
    // `version` column above is asc-only — wait, that's now asc-only.
    // The intent: prove that for a column with `sortDirections: ['desc']`,
    // `?sort=col` resolves to `col:asc` (the fallback) and then drops
    // because asc isn't in the allowlist. The hook does NOT silently
    // synthesize `col:desc` to "be charitable."
    const descOnly: DataTableColumnDef<MockRow>[] = [
      { id: 'metric', header: 'Metric', sortable: true, sortDirections: ['desc'] },
    ];
    currentSearch = 'sort=metric';
    const { result } = renderHook(() => useDataTableUrlState('mock', descOnly));
    expect(result.current.sort).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// chore_data_table_columnvisibility_tanstack item 4 — pageSize allowlist coercion
// ---------------------------------------------------------------------------
describe('useDataTableUrlState — pageSize validation', () => {
  it('coerces ?limit= values outside pageSizeOptions to defaultPageSize', () => {
    currentSearch = 'limit=99';
    const { result } = renderHook(() =>
      useDataTableUrlState('mock', columns, {
        defaultPageSize: 50,
        pageSizeOptions: [25, 50, 100, 200],
      }),
    );
    expect(result.current.pageSize).toBe(50);
  });

  it('accepts ?limit= values inside pageSizeOptions', () => {
    currentSearch = 'limit=100';
    const { result } = renderHook(() =>
      useDataTableUrlState('mock', columns, {
        defaultPageSize: 50,
        pageSizeOptions: [25, 50, 100, 200],
      }),
    );
    expect(result.current.pageSize).toBe(100);
  });

  it('accepts any positive ?limit= when pageSizeOptions is omitted (backward-compat)', () => {
    currentSearch = 'limit=99';
    const { result } = renderHook(() =>
      useDataTableUrlState('mock', columns, { defaultPageSize: 50 }),
    );
    expect(result.current.pageSize).toBe(99);
  });

  it('coerces non-numeric ?limit= to defaultPageSize regardless of pageSizeOptions', () => {
    currentSearch = 'limit=abc';
    const { result } = renderHook(() =>
      useDataTableUrlState('mock', columns, {
        defaultPageSize: 50,
        pageSizeOptions: [25, 50, 100],
      }),
    );
    expect(result.current.pageSize).toBe(50);
  });

  it('truncates fractional ?limit= to an integer (Gemini PR #132 finding)', () => {
    // `parseInt("100.5", 10)` returns 100, not NaN — caller gets a clean
    // integer even when a URL is hand-crafted with a fraction.
    currentSearch = 'limit=100.5';
    const { result } = renderHook(() =>
      useDataTableUrlState('mock', columns, {
        defaultPageSize: 50,
        pageSizeOptions: [25, 50, 100, 200],
      }),
    );
    expect(result.current.pageSize).toBe(100);
  });
});
