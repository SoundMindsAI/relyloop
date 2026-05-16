/**
 * Selection + bulk-action tests (feat_data_table_primitive Story 2.9 / FR-13 / AC-10).
 */

import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { DataTable } from '@/components/common/data-table';
import { DataTableBulkActions } from '@/components/common/data-table-bulk-actions';
import type { DataTableColumnDef } from '@/components/common/types';

interface Row {
  id: string;
  name: string;
}

const columns: DataTableColumnDef<Row>[] = [{ id: 'name', header: 'Name', accessorKey: 'name' }];

const rows: Row[] = [
  { id: 'r1', name: 'alpha' },
  { id: 'r2', name: 'beta' },
  { id: 'r3', name: 'gamma' },
];

function renderTable(props: Partial<Parameters<typeof DataTable<Row>>[0]> = {}) {
  return render(
    <DataTable<Row>
      tableId="mock"
      tableTestId="mock-table"
      rowTestId={(r) => `mock-row-${r.id}`}
      columns={columns}
      data={rows}
      isLoading={false}
      isError={false}
      has_more={false}
      next_cursor={null}
      emptyStateNoRows={{ title: 'Empty', message: '' }}
      {...props}
    />,
  );
}

describe('DataTable selection (Story 2.9)', () => {
  it('does NOT render selection checkboxes when selectable is false (default)', () => {
    renderTable();
    expect(screen.queryByTestId('data-table-select-all')).not.toBeInTheDocument();
    expect(screen.queryByTestId('data-table-select-row-r1')).not.toBeInTheDocument();
  });

  it('renders header + per-row checkboxes when selectable is true', () => {
    renderTable({ selectable: true });
    expect(screen.getByTestId('data-table-select-all')).toBeInTheDocument();
    expect(screen.getByTestId('data-table-select-row-r1')).toBeInTheDocument();
    expect(screen.getByTestId('data-table-select-row-r2')).toBeInTheDocument();
  });

  it('does not show the bulk-action toolbar when nothing is selected', () => {
    const action = { label: 'Cancel', onClick: vi.fn() };
    renderTable({ selectable: true, bulkActions: [action] });
    expect(screen.queryByTestId('data-table-bulk-actions')).not.toBeInTheDocument();
  });

  it('shows the bulk-action toolbar after ≥1 row is selected; counter reflects N', () => {
    const action = { label: 'Cancel', onClick: vi.fn() };
    renderTable({ selectable: true, bulkActions: [action] });
    fireEvent.click(screen.getByTestId('data-table-select-row-r1'));
    expect(screen.getByTestId('data-table-bulk-actions')).toBeInTheDocument();
    expect(screen.getByTestId('data-table-bulk-actions-count')).toHaveTextContent('1');
    fireEvent.click(screen.getByTestId('data-table-select-row-r3'));
    expect(screen.getByTestId('data-table-bulk-actions-count')).toHaveTextContent('2');
  });

  it('"select all on page" header checkbox toggles every row on the page', () => {
    const onSelectionChange = vi.fn();
    renderTable({
      selectable: true,
      bulkActions: [{ label: 'X', onClick: vi.fn() }],
      onSelectionChange,
    });
    fireEvent.click(screen.getByTestId('data-table-select-all'));
    expect(screen.getByTestId('data-table-bulk-actions-count')).toHaveTextContent('3');
    expect(onSelectionChange).toHaveBeenCalledWith(['r1', 'r2', 'r3']);
    fireEvent.click(screen.getByTestId('data-table-select-all'));
    expect(screen.queryByTestId('data-table-bulk-actions')).not.toBeInTheDocument();
  });
});

describe('DataTableBulkActions standalone', () => {
  it('passes selectedIds + clearSelection into action.onClick', () => {
    const onClick = vi.fn();
    const onClear = vi.fn();
    render(
      <DataTableBulkActions
        selectedIds={['r1', 'r2']}
        actions={[{ label: 'Cancel', onClick }]}
        onClear={onClear}
      />,
    );
    fireEvent.click(screen.getByTestId('data-table-bulk-action-0'));
    expect(onClick).toHaveBeenCalledWith(['r1', 'r2'], onClear);
  });

  it('Clear button calls onClear directly', () => {
    const onClear = vi.fn();
    render(
      <DataTableBulkActions
        selectedIds={['r1']}
        actions={[{ label: 'X', onClick: vi.fn() }]}
        onClear={onClear}
      />,
    );
    fireEvent.click(screen.getByTestId('data-table-bulk-actions-clear'));
    expect(onClear).toHaveBeenCalledTimes(1);
  });
});
