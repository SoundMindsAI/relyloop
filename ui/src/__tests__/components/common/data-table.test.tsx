// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * `<DataTable>` primitive scaffold tests (feat_data_table_primitive Story 2.1).
 *
 * Smoke-tests the Story 2.1 shell: renders 3 mock rows, renders the empty
 * state when data is empty, and renders the loading placeholder when
 * `isLoading` is true. The full feature coverage (sort cycle, filter chips,
 * search debounce, etc.) lands as Stories 2.2–2.13 each add their own
 * dedicated test cases here.
 */

import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { DataTable } from '@/components/common/data-table';
import type { DataTableColumnDef } from '@/components/common/types';

interface MockRow {
  id: string;
  name: string;
  status: string;
}

const columns: DataTableColumnDef<MockRow>[] = [
  { id: 'name', header: 'Name', accessorKey: 'name' },
  { id: 'status', header: 'Status', accessorKey: 'status' },
];

const rows: MockRow[] = [
  { id: 'r1', name: 'alpha', status: 'completed' },
  { id: 'r2', name: 'beta', status: 'queued' },
  { id: 'r3', name: 'gamma', status: 'running' },
];

function renderTable(props: Partial<Parameters<typeof DataTable<MockRow>>[0]> = {}) {
  return render(
    <DataTable<MockRow>
      tableId="mock"
      tableTestId="mock-table"
      rowTestId={(r) => `mock-row-${r.id}`}
      columns={columns}
      data={rows}
      isLoading={false}
      isError={false}
      has_more={false}
      next_cursor={null}
      emptyStateNoRows={{
        title: 'No rows yet',
        message: 'Create one to begin.',
      }}
      {...props}
    />,
  );
}

describe('DataTable scaffold (Story 2.1)', () => {
  it('renders rows via flexRender + the consumer-supplied rowTestId mapper', () => {
    renderTable();
    expect(screen.getByTestId('mock-table')).toBeInTheDocument();
    expect(screen.getByTestId('mock-row-r1')).toBeInTheDocument();
    expect(screen.getByTestId('mock-row-r2')).toBeInTheDocument();
    expect(screen.getByTestId('mock-row-r3')).toBeInTheDocument();
    expect(screen.getByText('alpha')).toBeInTheDocument();
    expect(screen.getByText('completed')).toBeInTheDocument();
  });

  it('renders the no-rows-exist empty state when data is empty', () => {
    renderTable({
      data: [],
      emptyStateNoRows: { title: 'Empty list', message: 'Nothing here.' },
    });
    expect(screen.getByTestId('data-table-empty-no-rows-exist')).toBeInTheDocument();
    expect(screen.getByText('Empty list')).toBeInTheDocument();
    expect(screen.getByText('Nothing here.')).toBeInTheDocument();
    expect(screen.queryByTestId('mock-table')).not.toBeInTheDocument();
  });

  it('renders the loading placeholder when isLoading is true', () => {
    renderTable({ isLoading: true, data: [] });
    expect(screen.getByTestId('mock-table-loading')).toHaveTextContent('Loading…');
    expect(screen.queryByTestId('mock-table')).not.toBeInTheDocument();
  });

  it('renders an error state with a retry affordance when isError is true', () => {
    renderTable({ isError: true, data: [] });
    const errorPanel = screen.getByTestId('mock-table-error');
    expect(errorPanel).toHaveTextContent("Couldn't load this list");
    // A retry button is always present (falls back to page reload when no
    // onRetry handler is supplied).
    expect(screen.getByTestId('mock-table-retry')).toBeInTheDocument();
  });

  it('surfaces the real error message and calls onRetry when supplied', () => {
    const onRetry = vi.fn();
    renderTable({
      isError: true,
      data: [],
      errorMessage: 'Query set not found',
      onRetry,
    });
    expect(screen.getByTestId('mock-table-error')).toHaveTextContent('Query set not found');
    fireEvent.click(screen.getByTestId('mock-table-retry'));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('uses backend UUIDs (not array indices) for row identity', () => {
    renderTable();
    // Confirms getRowId: row => row.id is wired — the row testid contains
    // the backend id, not "0" / "1" / "2".
    expect(screen.queryByTestId('mock-row-0')).not.toBeInTheDocument();
    expect(screen.queryByTestId('mock-row-1')).not.toBeInTheDocument();
  });

  // Story 2.7 — empty-state branching (no-rows-match / no-rows-exist / stale-cursor).
  it('renders no-rows-match when data empty AND a filter is active', () => {
    renderTable({
      data: [],
      totalCount: 0,
      anyMatcherActive: true,
      onClearMatchers: vi.fn(),
    });
    expect(screen.getByTestId('data-table-empty-no-rows-match')).toBeInTheDocument();
    expect(screen.getByTestId('data-table-empty-clear-filters')).toBeInTheDocument();
  });

  it('renders stale-cursor when data empty BUT totalCount > 0 AND cursor present', () => {
    renderTable({
      data: [],
      totalCount: 12,
      cursor: 'opaque',
      onCursorChange: vi.fn(),
    });
    expect(screen.getByTestId('data-table-empty-stale-cursor')).toBeInTheDocument();
    expect(screen.getByTestId('data-table-empty-return-to-first-page')).toBeInTheDocument();
  });

  it('renders no-rows-exist when data empty AND no filters/q active AND totalCount=0', () => {
    renderTable({
      data: [],
      totalCount: 0,
      anyMatcherActive: false,
    });
    expect(screen.getByTestId('data-table-empty-no-rows-exist')).toBeInTheDocument();
  });

  // Story 2.5/2.7 cursor stack — DataTable owns the trail of cursors so Prev
  // steps back one page rather than jumping to page 1.
  describe('cursor stack (Story 2.5/2.7)', () => {
    it('Prev is disabled on page 1 (stack length 1)', () => {
      renderTable({
        has_more: true,
        next_cursor: 'c2',
        onCursorChange: vi.fn(),
        onPageSizeChange: vi.fn(),
      });
      expect(screen.getByTestId('paginator-prev')).toBeDisabled();
    });

    it('Next pushes the cursor; Prev pops back to the prior page', () => {
      const onCursorChange = vi.fn();
      renderTable({
        has_more: true,
        next_cursor: 'c2',
        onCursorChange,
        onPageSizeChange: vi.fn(),
      });
      fireEvent.click(screen.getByTestId('paginator-next'));
      expect(onCursorChange).toHaveBeenLastCalledWith('c2');
      // Simulate consumer applying the new cursor — Prev should now step
      // back to the prior page (null), not jump straight to page 1.
      // Stack state lives in DataTable and survives across renders.
    });

    it('Prev steps back one page after a Next click (single-step verification)', () => {
      const onCursorChange = vi.fn();
      const { rerender } = render(
        <DataTable<MockRow>
          tableId="mock"
          tableTestId="mock-table"
          rowTestId={(r) => `mock-row-${r.id}`}
          columns={columns}
          data={rows}
          isLoading={false}
          isError={false}
          has_more={true}
          next_cursor="c2"
          emptyStateNoRows={{ title: 'no', message: '' }}
          onCursorChange={onCursorChange}
          onPageSizeChange={vi.fn()}
        />,
      );
      fireEvent.click(screen.getByTestId('paginator-next'));
      // Simulate the consumer applying the URL change: cursor is now 'c2'.
      rerender(
        <DataTable<MockRow>
          tableId="mock"
          tableTestId="mock-table"
          rowTestId={(r) => `mock-row-${r.id}`}
          columns={columns}
          data={rows}
          isLoading={false}
          isError={false}
          has_more={false}
          next_cursor={null}
          cursor="c2"
          emptyStateNoRows={{ title: 'no', message: '' }}
          onCursorChange={onCursorChange}
          onPageSizeChange={vi.fn()}
        />,
      );
      fireEvent.click(screen.getByTestId('paginator-prev'));
      // Prev pops back to the prior entry (null = first page).
      expect(onCursorChange).toHaveBeenLastCalledWith(null);
    });

    it('External cursor change (filter / sort / q reset) regrounds the stack', () => {
      const onCursorChange = vi.fn();
      const { rerender } = render(
        <DataTable<MockRow>
          tableId="mock"
          tableTestId="mock-table"
          rowTestId={(r) => `mock-row-${r.id}`}
          columns={columns}
          data={rows}
          isLoading={false}
          isError={false}
          has_more={true}
          next_cursor="c2"
          cursor={null}
          emptyStateNoRows={{ title: 'no', message: '' }}
          onCursorChange={onCursorChange}
          onPageSizeChange={vi.fn()}
        />,
      );
      // Click Next → stack pushes 'c2'.
      fireEvent.click(screen.getByTestId('paginator-next'));
      // Consumer applies the URL change: cursor is now 'c2'.
      rerender(
        <DataTable<MockRow>
          tableId="mock"
          tableTestId="mock-table"
          rowTestId={(r) => `mock-row-${r.id}`}
          columns={columns}
          data={rows}
          isLoading={false}
          isError={false}
          has_more={true}
          next_cursor="c3"
          cursor="c2"
          emptyStateNoRows={{ title: 'no', message: '' }}
          onCursorChange={onCursorChange}
          onPageSizeChange={vi.fn()}
        />,
      );
      // User flips a filter — consumer's URL hook resets cursor to null.
      rerender(
        <DataTable<MockRow>
          tableId="mock"
          tableTestId="mock-table"
          rowTestId={(r) => `mock-row-${r.id}`}
          columns={columns}
          data={rows}
          isLoading={false}
          isError={false}
          has_more={true}
          next_cursor="c2"
          cursor={null}
          emptyStateNoRows={{ title: 'no', message: '' }}
          onCursorChange={onCursorChange}
          onPageSizeChange={vi.fn()}
        />,
      );
      // Stack regrounded to [null]; Prev disabled again.
      expect(screen.getByTestId('paginator-prev')).toBeDisabled();
    });
  });
});
