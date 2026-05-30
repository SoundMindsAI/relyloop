// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * `<DataTableSortHeader>` cycle-logic tests (feat_data_table_primitive Story 2.2).
 *
 * Covers FR-4's three-state cycle + the per-column `firstClickDirection` and
 * `sortDirections` constraints, including the trials-specific
 * `optuna_trial_number_asc`-only case captured at AC-13.
 */

import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { DataTableSortHeader, nextSortValue } from '@/components/common/data-table-sort-header';

describe('nextSortValue (pure cycle logic)', () => {
  it('default firstClickDirection asc: unsorted → asc → desc → unsorted', () => {
    expect(nextSortValue(null, 'name', 'asc', ['asc', 'desc'])).toBe('name:asc');
    expect(nextSortValue('asc', 'name', 'asc', ['asc', 'desc'])).toBe('name:desc');
    expect(nextSortValue('desc', 'name', 'asc', ['asc', 'desc'])).toBe(null);
  });

  it('firstClickDirection desc: unsorted → desc → asc → unsorted', () => {
    expect(nextSortValue(null, 'best_metric', 'desc', ['asc', 'desc'])).toBe('best_metric:desc');
    expect(nextSortValue('desc', 'best_metric', 'desc', ['asc', 'desc'])).toBe('best_metric:asc');
    expect(nextSortValue('asc', 'best_metric', 'desc', ['asc', 'desc'])).toBe(null);
  });

  it('sortDirections=[asc] only: unsorted ↔ asc (no desc reachable)', () => {
    // Models the trials.optuna_trial_number case — backend Literal only has
    // `optuna_trial_number_asc`, no `_desc`. Cycle skips desc.
    expect(nextSortValue(null, 'optuna_trial_number', 'asc', ['asc'])).toBe(
      'optuna_trial_number:asc',
    );
    expect(nextSortValue('asc', 'optuna_trial_number', 'asc', ['asc'])).toBe(null);
  });

  it('sortDirections=[desc] only: unsorted ↔ desc', () => {
    expect(nextSortValue(null, 'best_metric', 'desc', ['desc'])).toBe('best_metric:desc');
    expect(nextSortValue('desc', 'best_metric', 'desc', ['desc'])).toBe(null);
  });
});

describe('DataTableSortHeader interaction', () => {
  it('clicking calls onSortChange with the next value', () => {
    const onSortChange = vi.fn();
    render(
      <DataTableSortHeader
        label="Name"
        sortKey="name"
        activeSort={null}
        onSortChange={onSortChange}
      />,
    );
    const btn = screen.getByTestId('data-table-sort-name');
    fireEvent.click(btn);
    expect(onSortChange).toHaveBeenCalledWith('name:asc');
  });

  it('shows the correct aria-sort attribute and chevron for asc', () => {
    render(
      <DataTableSortHeader
        label="Name"
        sortKey="name"
        activeSort="name:asc"
        onSortChange={vi.fn()}
      />,
    );
    const btn = screen.getByTestId('data-table-sort-name');
    expect(btn).toHaveAttribute('data-active-dir', 'asc');
    expect(screen.getByText('Sorted ascending')).toBeInTheDocument();
  });

  it('shows aria-sort=none + the unsorted chevron when not active', () => {
    render(
      <DataTableSortHeader
        label="Name"
        sortKey="name"
        activeSort="other_col:asc"
        onSortChange={vi.fn()}
      />,
    );
    const btn = screen.getByTestId('data-table-sort-name');
    expect(btn).toHaveAttribute('data-active-dir', 'none');
    expect(screen.getByText('Not sorted')).toBeInTheDocument();
  });
});
