// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * "Sorted by relevance" indicator tests (feat_fts_rank_ordering FR-4 / AC-8).
 *
 * The pill renders iff a search is active (`q` non-empty) AND no explicit
 * column sort is applied — mirroring the backend `rank_active(q, parsed_sort)`
 * predicate that drives the ts_rank ORDER BY.
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { DataTable } from '@/components/common/data-table';
import type { DataTableColumnDef } from '@/components/common/types';
import { TooltipProvider } from '@/components/ui/tooltip';

interface MockRow {
  id: string;
  name: string;
}

const columns: DataTableColumnDef<MockRow>[] = [
  { id: 'name', header: 'Name', accessorKey: 'name', sortKey: 'name' },
];
const rows: MockRow[] = [{ id: 'r1', name: 'alpha' }];

function renderTable(props: Partial<Parameters<typeof DataTable<MockRow>>[0]> = {}) {
  return render(
    <TooltipProvider>
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
        searchable
        onQChange={vi.fn()}
        emptyStateNoRows={{ title: 'No rows', message: 'Create one.' }}
        {...props}
      />
    </TooltipProvider>,
  );
}

describe('FTS relevance indicator (AC-8)', () => {
  it('renders when q is non-empty and no explicit sort is active', () => {
    renderTable({ q: 'phones', sort: null });
    expect(screen.getByTestId('fts-relevance-indicator')).toBeInTheDocument();
    expect(screen.getByTestId('fts-relevance-indicator')).toHaveTextContent('Sorted by relevance');
  });

  it('does NOT render when an explicit sort is active (sort overrides rank)', () => {
    renderTable({ q: 'phones', sort: 'name:asc' });
    expect(screen.queryByTestId('fts-relevance-indicator')).not.toBeInTheDocument();
  });

  it('does NOT render when q is empty/null', () => {
    renderTable({ q: null, sort: null });
    expect(screen.queryByTestId('fts-relevance-indicator')).not.toBeInTheDocument();
  });

  it('does NOT render when q is whitespace-only', () => {
    renderTable({ q: '   ', sort: null });
    expect(screen.queryByTestId('fts-relevance-indicator')).not.toBeInTheDocument();
  });
});
