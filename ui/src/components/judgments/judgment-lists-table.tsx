// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

/**
 * `<JudgmentListsTable>` — thin DataTable consumer for the /judgments index.
 * No sort/search (the list hook is cursor/limit only).
 */
import { DataTable } from '@/components/common/data-table';
import { judgmentListsColumns } from '@/components/judgments/judgment-lists-table.column-config';
import type { DataTableUrlStateApi } from '@/hooks/use-data-table-url-state';
import type { JudgmentListSummary } from '@/lib/api/judgments';

export interface JudgmentListsTableProps {
  rows: readonly JudgmentListSummary[];
  totalCount?: number;
  has_more: boolean;
  next_cursor: string | null;
  isLoading: boolean;
  isError: boolean;
  urlState: DataTableUrlStateApi;
}

export function JudgmentListsTable({
  rows,
  totalCount,
  has_more,
  next_cursor,
  isLoading,
  isError,
  urlState,
}: JudgmentListsTableProps) {
  return (
    <DataTable<JudgmentListSummary>
      tableId="judgment-lists"
      tableTestId="judgment-lists-table"
      rowTestId={(r) => `judgment-list-row-${r.id}`}
      columns={judgmentListsColumns}
      data={rows}
      isLoading={isLoading}
      isError={isError}
      totalCount={totalCount}
      has_more={has_more}
      next_cursor={next_cursor}
      cursor={urlState.cursor}
      pageSize={urlState.pageSize}
      onCursorChange={urlState.setCursor}
      onPageSizeChange={urlState.setPageSize}
      onClearMatchers={urlState.clearAllMatchers}
      anyMatcherActive={urlState.anyMatcherActive}
      emptyStateNoRows={{
        title: 'No judgment lists yet',
        message: 'Generate a judgment list from a query set (LLM-as-judge) or from UBI click data.',
      }}
      emptyStateNoMatch={{
        title: 'No judgment lists match',
        message: 'No judgment lists match the current filters.',
      }}
    />
  );
}
