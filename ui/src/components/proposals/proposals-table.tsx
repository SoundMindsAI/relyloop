'use client';

/**
 * `<ProposalsTable>` thin DataTable consumer
 * (feat_data_table_primitive Story 3.2).
 *
 * Renders the 7-column proposals list via the shared `<DataTable>` primitive
 * with `proposalsColumns`. URL state owned by `useDataTableUrlState` at
 * `/proposals/page.tsx`. `searchable={false}` per spec §3 — proposals has no
 * FTS.
 */
import { DataTable } from '@/components/common/data-table';
import { proposalsColumns } from '@/components/proposals/proposals-table.column-config';
import type { DataTableUrlStateApi } from '@/hooks/use-data-table-url-state';
import type { ProposalSummary } from '@/lib/api/proposals';

export interface ProposalsTableProps {
  rows: readonly ProposalSummary[];
  totalCount?: number;
  has_more: boolean;
  next_cursor: string | null;
  isLoading: boolean;
  isError: boolean;
  urlState: DataTableUrlStateApi;
  /** Optional override for the no-match empty state (e.g., custom copy when
   * the "Currently live only" filter is active). */
  emptyStateNoMatch?: { title: string; message: string };
}

export function ProposalsTable({
  rows,
  totalCount,
  has_more,
  next_cursor,
  isLoading,
  isError,
  urlState,
  emptyStateNoMatch,
}: ProposalsTableProps) {
  return (
    <DataTable<ProposalSummary>
      tableId="proposals"
      tableTestId="proposals-table"
      rowTestId={(r) => `proposal-row-${r.id}`}
      columns={proposalsColumns}
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
        title: 'No proposals yet',
        message: 'They appear automatically when studies complete.',
      }}
      emptyStateNoMatch={
        emptyStateNoMatch ?? {
          title: 'No proposals match',
          message: 'No proposals match the current filters.',
        }
      }
    />
  );
}
