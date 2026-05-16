/**
 * Column visibility + density toggle tests
 * (feat_data_table_primitive Stories 2.10 + 2.11 / FR-14 + FR-15).
 */

import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  DataTableColumnVisibility,
  type ColumnVisibilityItem,
} from '@/components/common/data-table-column-visibility';
import {
  DataTableDensityToggle,
  type DataTableDensity,
} from '@/components/common/data-table-density-toggle';

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
