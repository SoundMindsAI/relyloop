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
    filter: { kind: 'enum', wireValues: ['queued', 'running'], sourceOfTruth: 'test' },
  },
  {
    id: 'source',
    header: 'Source',
    filter: { kind: 'enum', wireValues: ['llm', 'human'], sourceOfTruth: 'test' },
  },
];

const pushMock = vi.fn();
const replaceMock = vi.fn();
let currentSearch = '';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: pushMock, replace: replaceMock }),
  useSearchParams: () => new URLSearchParams(currentSearch),
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
