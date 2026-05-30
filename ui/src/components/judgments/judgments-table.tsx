// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

/**
 * `<JudgmentsTable>` thin DataTable consumer
 * (feat_data_table_primitive Story 3.6).
 *
 * Per-list judgments view: searchable=false (no FTS on per-list endpoint).
 * Filter on source (URL-backed via ?source=), sort on rating + source.
 * The OverridePopover lives in the cell renderer of the Actions column
 * (see useJudgmentsColumns).
 */
import { DataTable } from '@/components/common/data-table';
import { useJudgmentsColumns } from '@/components/judgments/judgments-table.column-config';
import type { DataTableUrlStateApi } from '@/hooks/use-data-table-url-state';
import type { JudgmentRow } from '@/lib/api/judgments';

export interface JudgmentsTableProps {
  rows: readonly JudgmentRow[];
  listId: string;
  totalCount?: number;
  has_more: boolean;
  next_cursor: string | null;
  isLoading: boolean;
  isError: boolean;
  urlState: DataTableUrlStateApi;
}

export function JudgmentsTable({
  rows,
  listId,
  totalCount,
  has_more,
  next_cursor,
  isLoading,
  isError,
  urlState,
}: JudgmentsTableProps) {
  const columns = useJudgmentsColumns(listId);
  return (
    <DataTable<JudgmentRow>
      tableId={`judgments-${listId}`}
      tableTestId="judgments-table"
      rowTestId={(r) => `judgment-row-${r.id}`}
      columns={columns}
      data={rows}
      isLoading={isLoading}
      isError={isError}
      totalCount={totalCount}
      has_more={has_more}
      next_cursor={next_cursor}
      sort={urlState.sort}
      onSortChange={urlState.setSort}
      filters={urlState.filters}
      onFilterChange={urlState.setFilter}
      cursor={urlState.cursor}
      pageSize={urlState.pageSize}
      onCursorChange={urlState.setCursor}
      onPageSizeChange={urlState.setPageSize}
      onClearMatchers={urlState.clearAllMatchers}
      anyMatcherActive={urlState.anyMatcherActive}
      emptyStateNoRows={{
        title: 'No judgments yet',
        message: 'Generate judgments via the calibration modal.',
      }}
      emptyStateNoMatch={{
        title: 'No judgments match',
        message: 'No judgments match the current filters.',
      }}
    />
  );
}
