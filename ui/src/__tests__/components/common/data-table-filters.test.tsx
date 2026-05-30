// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Filter chips + FK-select tests (feat_data_table_primitive Story 2.3 / FR-5).
 */

import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { DataTableFilterChips } from '@/components/common/data-table-filter-chips';
import { DataTableFkSelect } from '@/components/common/data-table-fk-select';

describe('DataTableFilterChips', () => {
  const wireValues = ['queued', 'running', 'completed'] as const;

  it('renders an "all" chip plus one chip per wire value', () => {
    render(
      <DataTableFilterChips
        columnId="status"
        wireValues={wireValues}
        value={null}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByTestId('filter-chip-status-all')).toBeInTheDocument();
    expect(screen.getByTestId('filter-chip-status-queued')).toBeInTheDocument();
    expect(screen.getByTestId('filter-chip-status-running')).toBeInTheDocument();
    expect(screen.getByTestId('filter-chip-status-completed')).toBeInTheDocument();
  });

  it('marks the active chip with data-active="true"; "all" is active when value is null', () => {
    render(
      <DataTableFilterChips
        columnId="status"
        wireValues={wireValues}
        value={null}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByTestId('filter-chip-status-all')).toHaveAttribute('data-active', 'true');
    expect(screen.getByTestId('filter-chip-status-queued')).toHaveAttribute('data-active', 'false');
  });

  it('marks the matching chip active when value is non-null', () => {
    render(
      <DataTableFilterChips
        columnId="status"
        wireValues={wireValues}
        value="running"
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByTestId('filter-chip-status-running')).toHaveAttribute('data-active', 'true');
  });

  it('calls onChange with the wire value when a non-all chip is clicked', () => {
    const onChange = vi.fn();
    render(
      <DataTableFilterChips
        columnId="status"
        wireValues={wireValues}
        value={null}
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByTestId('filter-chip-status-completed'));
    expect(onChange).toHaveBeenCalledWith('completed');
  });

  it('calls onChange(null) when the "all" chip is clicked', () => {
    const onChange = vi.fn();
    render(
      <DataTableFilterChips
        columnId="status"
        wireValues={wireValues}
        value="running"
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByTestId('filter-chip-status-all'));
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it('disables all chips when isLoading is true', () => {
    render(
      <DataTableFilterChips
        columnId="status"
        wireValues={wireValues}
        value={null}
        onChange={vi.fn()}
        isLoading
      />,
    );
    expect(screen.getByTestId('filter-chip-status-all')).toBeDisabled();
    expect(screen.getByTestId('filter-chip-status-queued')).toBeDisabled();
  });
});

describe('DataTableFkSelect', () => {
  const fakeUseOptions =
    (data: { id: string; label: string }[], isLoading = false) =>
    () => ({ data, isLoading });

  it('renders "(loading…)" placeholder while isLoading is true', () => {
    render(
      <DataTableFkSelect
        columnId="cluster"
        useOptions={fakeUseOptions([], true)}
        value={null}
        onChange={vi.fn()}
      />,
    );
    const select = screen.getByTestId('fk-select-cluster');
    expect(select).toBeDisabled();
    expect(select).toHaveTextContent('(loading…)');
  });

  it('renders one option per FK entry plus the placeholder', () => {
    render(
      <DataTableFkSelect
        columnId="cluster"
        useOptions={fakeUseOptions([
          { id: 'c1', label: 'prod-es' },
          { id: 'c2', label: 'staging-os' },
        ])}
        value={null}
        onChange={vi.fn()}
        placeholder="All clusters"
      />,
    );
    const select = screen.getByTestId('fk-select-cluster');
    expect(select).toHaveTextContent('All clusters');
    expect(screen.getByText('prod-es')).toBeInTheDocument();
    expect(screen.getByText('staging-os')).toBeInTheDocument();
  });

  it('calls onChange with the option id on selection; null on placeholder', () => {
    const onChange = vi.fn();
    render(
      <DataTableFkSelect
        columnId="cluster"
        useOptions={fakeUseOptions([
          { id: 'c1', label: 'prod-es' },
          { id: 'c2', label: 'staging-os' },
        ])}
        value={null}
        onChange={onChange}
      />,
    );
    const select = screen.getByTestId('fk-select-cluster') as HTMLSelectElement;
    fireEvent.change(select, { target: { value: 'c2' } });
    expect(onChange).toHaveBeenCalledWith('c2');
    fireEvent.change(select, { target: { value: '' } });
    expect(onChange).toHaveBeenCalledWith(null);
  });
});
