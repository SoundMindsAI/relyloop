// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

/**
 * `<StudiesTable>` thin DataTable consumer
 * (feat_data_table_primitive Story 3.1).
 *
 * Was a hand-rolled `<Table>` rendering 6 columns; now defers to the shared
 * `<DataTable>` primitive with `studiesColumns`. URL-backed search / sort /
 * status filter / cursor pagination is owned by the parent
 * `/studies/page.tsx` via `useDataTableUrlState`, and threaded in as props
 * here (controlled-component contract per spec FR-8).
 */
import { DataTable } from '@/components/common/data-table';
import { studiesColumns } from '@/components/studies/studies-table.column-config';
import type { StudySummary } from '@/lib/api/studies';
import type { DataTableUrlStateApi } from '@/hooks/use-data-table-url-state';

export interface StudiesTableProps {
  rows: readonly StudySummary[];
  totalCount?: number;
  has_more: boolean;
  next_cursor: string | null;
  isLoading: boolean;
  isError: boolean;
  urlState: DataTableUrlStateApi;
}

export function StudiesTable({
  rows,
  totalCount,
  has_more,
  next_cursor,
  isLoading,
  isError,
  urlState,
}: StudiesTableProps) {
  return (
    <DataTable<StudySummary>
      tableId="studies"
      tableTestId="studies-table"
      rowTestId={(r) => `study-row-${r.id}`}
      columns={studiesColumns}
      data={rows}
      isLoading={isLoading}
      isError={isError}
      totalCount={totalCount}
      has_more={has_more}
      next_cursor={next_cursor}
      searchable
      sort={urlState.sort}
      onSortChange={urlState.setSort}
      filters={urlState.filters}
      onFilterChange={urlState.setFilter}
      q={urlState.q}
      onQChange={urlState.setQ}
      cursor={urlState.cursor}
      pageSize={urlState.pageSize}
      onCursorChange={urlState.setCursor}
      onPageSizeChange={urlState.setPageSize}
      onClearMatchers={urlState.clearAllMatchers}
      anyMatcherActive={urlState.anyMatcherActive}
      emptyStateNoRows={{
        title: 'No studies yet',
        message: 'Create a study to start tuning.',
      }}
      emptyStateNoMatch={{
        title: 'No studies match',
        message: 'No studies match the current filters.',
      }}
    />
  );
}
