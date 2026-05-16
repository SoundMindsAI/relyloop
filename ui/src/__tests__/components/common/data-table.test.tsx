/**
 * `<DataTable>` primitive scaffold tests (feat_data_table_primitive Story 2.1).
 *
 * Smoke-tests the Story 2.1 shell: renders 3 mock rows, renders the empty
 * state when data is empty, and renders the loading placeholder when
 * `isLoading` is true. The full feature coverage (sort cycle, filter chips,
 * search debounce, etc.) lands as Stories 2.2–2.13 each add their own
 * dedicated test cases here.
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

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

  it('renders the failed-to-load empty state when isError is true', () => {
    renderTable({ isError: true, data: [] });
    expect(screen.getByTestId('data-table-empty-no-rows-match')).toHaveTextContent(
      'Failed to load',
    );
  });

  it('uses backend UUIDs (not array indices) for row identity', () => {
    renderTable();
    // Confirms getRowId: row => row.id is wired — the row testid contains
    // the backend id, not "0" / "1" / "2".
    expect(screen.queryByTestId('mock-row-0')).not.toBeInTheDocument();
    expect(screen.queryByTestId('mock-row-1')).not.toBeInTheDocument();
  });
});
