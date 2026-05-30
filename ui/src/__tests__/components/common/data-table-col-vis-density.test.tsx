// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Column visibility + density toggle tests
 * (feat_data_table_primitive Stories 2.10 + 2.11 / FR-14 + FR-15).
 */

import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { DataTable } from '@/components/common/data-table';
import {
  DataTableColumnVisibility,
  type ColumnVisibilityItem,
} from '@/components/common/data-table-column-visibility';
import {
  DataTableDensityToggle,
  type DataTableDensity,
} from '@/components/common/data-table-density-toggle';
import type { DataTableColumnDef } from '@/components/common/types';

beforeEach(() => {
  // Reset localStorage between tests so density / col-vis defaults stay clean.
  try {
    window.localStorage.clear();
  } catch {
    /* ignore */
  }
});
afterEach(() => {
  try {
    window.localStorage.clear();
  } catch {
    /* ignore */
  }
});

describe('DataTableColumnVisibility', () => {
  const items: ColumnVisibilityItem[] = [
    { id: 'name', label: 'Name', hidden: false },
    { id: 'created_at', label: 'Created', hidden: true },
    { id: 'cluster_id', label: 'Cluster', hidden: false, sticky: true },
  ];

  it('renders only non-sticky columns in the popover (sticky filtered out)', () => {
    render(<DataTableColumnVisibility items={items} onToggle={vi.fn()} />);
    fireEvent.click(screen.getByTestId('data-table-column-visibility'));
    expect(screen.getByTestId('data-table-column-visibility-row-name')).toBeInTheDocument();
    expect(screen.getByTestId('data-table-column-visibility-row-created_at')).toBeInTheDocument();
    expect(
      screen.queryByTestId('data-table-column-visibility-row-cluster_id'),
    ).not.toBeInTheDocument();
  });

  it('checkbox reflects hidden state (true=hidden → unchecked)', () => {
    render(<DataTableColumnVisibility items={items} onToggle={vi.fn()} />);
    fireEvent.click(screen.getByTestId('data-table-column-visibility'));
    const nameToggle = screen.getByTestId(
      'data-table-column-visibility-toggle-name',
    ) as HTMLInputElement;
    expect(nameToggle.checked).toBe(true); // hidden=false → visible → checked
    const createdToggle = screen.getByTestId(
      'data-table-column-visibility-toggle-created_at',
    ) as HTMLInputElement;
    expect(createdToggle.checked).toBe(false); // hidden=true → not checked
  });

  it('calls onToggle with the column id on click', () => {
    const onToggle = vi.fn();
    render(<DataTableColumnVisibility items={items} onToggle={onToggle} />);
    fireEvent.click(screen.getByTestId('data-table-column-visibility'));
    fireEvent.click(screen.getByTestId('data-table-column-visibility-toggle-name'));
    expect(onToggle).toHaveBeenCalledWith('name');
  });
});

describe('DataTableDensityToggle', () => {
  function Wrapper() {
    const [d, setD] = useStateForTest<DataTableDensity>('comfortable');
    return <DataTableDensityToggle density={d} onChange={setD} />;
  }
  // Mini useState replacement avoids cyclic React import in jsdom mode.
  function useStateForTest<T>(initial: T): [T, (next: T) => void] {
    const ref = { current: initial };
    const setter = (next: T) => {
      ref.current = next;
    };
    return [ref.current, setter];
  }

  it('renders both buttons with the active one marked', () => {
    render(<DataTableDensityToggle density="comfortable" onChange={vi.fn()} />);
    expect(screen.getByTestId('data-table-density-toggle-comfortable')).toHaveAttribute(
      'data-active',
      'true',
    );
    expect(screen.getByTestId('data-table-density-toggle-compact')).toHaveAttribute(
      'data-active',
      'false',
    );
  });

  it('calls onChange with the clicked density', () => {
    const onChange = vi.fn();
    render(<DataTableDensityToggle density="comfortable" onChange={onChange} />);
    fireEvent.click(screen.getByTestId('data-table-density-toggle-compact'));
    expect(onChange).toHaveBeenCalledWith('compact');
  });
});

// ---------------------------------------------------------------------------
// Integration through <DataTable> (Story 2.10 + 2.11 DoD):
// hide-column round-trip + density localStorage persistence.
// ---------------------------------------------------------------------------

describe('DataTable integration — column visibility + density (Stories 2.10/2.11)', () => {
  interface Row {
    id: string;
    name: string;
    status: string;
  }

  const integrationColumns: DataTableColumnDef<Row>[] = [
    { id: 'name', header: 'Name', accessorKey: 'name' },
    { id: 'status', header: 'Status', accessorKey: 'status' },
  ];

  const integrationRows: Row[] = [
    { id: 'r1', name: 'alpha', status: 'completed' },
    { id: 'r2', name: 'beta', status: 'queued' },
  ];

  function renderIntegrationTable() {
    return render(
      <DataTable<Row>
        tableId="integration-tbl"
        tableTestId="integration-table"
        rowTestId={(r) => `integration-row-${r.id}`}
        columns={integrationColumns}
        data={integrationRows}
        isLoading={false}
        isError={false}
        has_more={false}
        next_cursor={null}
        emptyStateNoRows={{ title: 'Empty', message: '' }}
      />,
    );
  }

  it('toggling a column off via the menu removes its cells and persists to localStorage', () => {
    renderIntegrationTable();
    // Status column visible by default.
    expect(screen.getAllByText('completed').length).toBeGreaterThan(0);
    fireEvent.click(screen.getByTestId('data-table-column-visibility'));
    fireEvent.click(screen.getByTestId('data-table-column-visibility-toggle-status'));
    // Status cells gone.
    expect(screen.queryByText('completed')).not.toBeInTheDocument();
    // localStorage holds the hidden id.
    const raw = window.localStorage.getItem('relyloop:datatable:integration-tbl:hidden-columns');
    expect(raw).toBeTruthy();
    expect(JSON.parse(raw!)).toContain('status');
  });

  it('mounts with a pre-existing localStorage hidden entry — column starts hidden', () => {
    window.localStorage.setItem(
      'relyloop:datatable:integration-tbl:hidden-columns',
      JSON.stringify(['status']),
    );
    renderIntegrationTable();
    expect(screen.queryByText('completed')).not.toBeInTheDocument();
    expect(screen.getByText('alpha')).toBeInTheDocument();
  });

  it('tampered localStorage cannot hide a column with hideable: false', () => {
    window.localStorage.setItem(
      'relyloop:datatable:integration-tbl:hidden-columns',
      JSON.stringify(['name', 'status']),
    );
    // Override: mark `name` as non-hideable.
    const cols: DataTableColumnDef<Row>[] = [
      { id: 'name', header: 'Name', accessorKey: 'name', hideable: false },
      { id: 'status', header: 'Status', accessorKey: 'status' },
    ];
    render(
      <DataTable<Row>
        tableId="integration-tbl"
        tableTestId="integration-table"
        rowTestId={(r) => `integration-row-${r.id}`}
        columns={cols}
        data={integrationRows}
        isLoading={false}
        isError={false}
        has_more={false}
        next_cursor={null}
        emptyStateNoRows={{ title: 'Empty', message: '' }}
      />,
    );
    // Name cells are still rendered despite localStorage including it.
    expect(screen.getByText('alpha')).toBeInTheDocument();
    expect(screen.getByText('beta')).toBeInTheDocument();
  });

  it('density toggle persists to localStorage and hydrates on mount', () => {
    const { unmount } = renderIntegrationTable();
    fireEvent.click(screen.getByTestId('data-table-density-toggle-compact'));
    expect(window.localStorage.getItem('relyloop:datatable:integration-tbl:density')).toBe(
      'compact',
    );
    unmount();
    // Remount — density should hydrate to 'compact'.
    renderIntegrationTable();
    expect(screen.getByTestId('data-table-density-toggle-compact')).toHaveAttribute(
      'data-active',
      'true',
    );
  });
});
