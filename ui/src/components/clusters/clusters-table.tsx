'use client';

/**
 * `<ClustersTable>` thin DataTable consumer
 * (feat_data_table_primitive Story 3.3).
 *
 * Renders the 6-column clusters list via the shared `<DataTable>` primitive
 * with `clustersColumns`. URL state owned by `useDataTableUrlState` at
 * `/clusters/page.tsx`. FTS `?q=` searches `name + base_url`.
 */
import { DataTable } from '@/components/common/data-table';
import { clustersColumns } from '@/components/clusters/clusters-table.column-config';
import type { DataTableUrlStateApi } from '@/hooks/use-data-table-url-state';
import type { ClusterSummary } from '@/lib/api/clusters';

export interface ClustersTableProps {
  rows: readonly ClusterSummary[];
  totalCount?: number;
  has_more: boolean;
  next_cursor: string | null;
  isLoading: boolean;
  isError: boolean;
  urlState: DataTableUrlStateApi;
  onRegisterCluster?: () => void;
}

export function ClustersTable({
  rows,
  totalCount,
  has_more,
  next_cursor,
  isLoading,
  isError,
  urlState,
  onRegisterCluster,
}: ClustersTableProps) {
  return (
    <DataTable<ClusterSummary>
      tableId="clusters"
      tableTestId="clusters-table"
      rowTestId={(r) => `cluster-row-${r.id}`}
      columns={clustersColumns}
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
        title: 'No clusters registered',
        message: 'Click "Register cluster" to add one.',
      }}
      emptyStateNoMatch={{
        title: 'No clusters match',
        message: 'No clusters match the current filters.',
      }}
    />
  );
}
