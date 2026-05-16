/**
 * Keyboard navigation tests (feat_data_table_primitive Story 2.12 / FR-16 / AC-12).
 *
 * Covers the roving-tabindex shape, Arrow Up/Down wrap-around, Enter →
 * `onRowActivate`, Space → selection toggle when `selectable`, and the
 * `keyboardNav={false}` escape hatch.
 */

import '@testing-library/jest-dom/vitest';
import { render, screen } from '@testing-library/react';
import { userEvent } from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { DataTable } from '@/components/common/data-table';
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

describe('DataTable keyboard navigation (Story 2.12)', () => {
  it('renders a roving tabindex: row 0 has tabIndex=0, others have tabIndex=-1', () => {
    renderTable();
    expect(screen.getByTestId('mock-row-r1')).toHaveAttribute('tabindex', '0');
    expect(screen.getByTestId('mock-row-r2')).toHaveAttribute('tabindex', '-1');
    expect(screen.getByTestId('mock-row-r3')).toHaveAttribute('tabindex', '-1');
  });

  it('Arrow Down advances focus to the next row', async () => {
    const user = userEvent.setup();
    renderTable();
    const row0 = screen.getByTestId('mock-row-r1');
    row0.focus();
    expect(row0).toHaveFocus();
    await user.keyboard('{ArrowDown}');
    expect(screen.getByTestId('mock-row-r2')).toHaveFocus();
  });

  it('Arrow Up from the first row wraps to the last row', async () => {
    const user = userEvent.setup();
    renderTable();
    screen.getByTestId('mock-row-r1').focus();
    await user.keyboard('{ArrowUp}');
    expect(screen.getByTestId('mock-row-r3')).toHaveFocus();
  });

  it('Arrow Down from the last row wraps to the first row', async () => {
    const user = userEvent.setup();
    renderTable();
    screen.getByTestId('mock-row-r3').focus();
    await user.keyboard('{ArrowDown}');
    expect(screen.getByTestId('mock-row-r1')).toHaveFocus();
  });

  it('Enter on a row calls onRowActivate with the row id', async () => {
    const onRowActivate = vi.fn();
    const user = userEvent.setup();
    renderTable({ onRowActivate });
    screen.getByTestId('mock-row-r2').focus();
    await user.keyboard('{Enter}');
    expect(onRowActivate).toHaveBeenCalledWith('r2');
  });

  it('Space toggles selection when selectable=true', async () => {
    const user = userEvent.setup();
    renderTable({ selectable: true, bulkActions: [{ label: 'X', onClick: vi.fn() }] });
    screen.getByTestId('mock-row-r1').focus();
    await user.keyboard(' ');
    expect(screen.getByTestId('data-table-bulk-actions-count')).toHaveTextContent('1');
  });

  it('Space does NOT toggle selection when selectable=false', async () => {
    const user = userEvent.setup();
    renderTable();
    screen.getByTestId('mock-row-r1').focus();
    await user.keyboard(' ');
    expect(screen.queryByTestId('data-table-bulk-actions')).not.toBeInTheDocument();
  });

  it('keyboardNav={false} disables tabindex and Arrow handling', async () => {
    const user = userEvent.setup();
    renderTable({ keyboardNav: false });
    const row0 = screen.getByTestId('mock-row-r1');
    expect(row0).not.toHaveAttribute('tabindex');
    // Manually focus (no roving tabindex when disabled) — Arrow should be a no-op.
    row0.focus();
    await user.keyboard('{ArrowDown}');
    expect(screen.getByTestId('mock-row-r2')).not.toHaveFocus();
  });
});
