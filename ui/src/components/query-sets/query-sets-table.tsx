'use client';

/**
 * `<QuerySetsTable>` thin DataTable consumer
 * (feat_data_table_primitive Story 3.5).
 */
import { DataTable } from '@/components/common/data-table';
import { querySetsColumns } from '@/components/query-sets/query-sets-table.column-config';
import type { DataTableUrlStateApi } from '@/hooks/use-data-table-url-state';
import type { QuerySetSummary } from '@/lib/api/query-sets';

export interface QuerySetsTableProps {
  rows: readonly QuerySetSummary[];
  totalCount?: number;
  has_more: boolean;
  next_cursor: string | null;
  isLoading: boolean;
  isError: boolean;
  urlState: DataTableUrlStateApi;
}

export function QuerySetsTable({
  rows,
  totalCount,
  has_more,
  next_cursor,
  isLoading,
  isError,
  urlState,
}: QuerySetsTableProps) {
  return (
    <DataTable<QuerySetSummary>
      tableId="query-sets"
      tableTestId="query-sets-table"
      rowTestId={(r) => `query-set-row-${r.id}`}
      columns={querySetsColumns}
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
        title: 'No query sets yet',
        message: 'Click "Create query set" to add one.',
      }}
      emptyStateNoMatch={{
        title: 'No query sets match',
        message: 'No query sets match the current filters.',
      }}
    />
  );
}
