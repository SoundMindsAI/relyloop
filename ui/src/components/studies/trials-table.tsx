'use client';

/**
 * `<TrialsTable>` thin DataTable consumer
 * (feat_data_table_primitive Story 3.7).
 *
 * Per-study trials view: searchable=false, no filters. Sort uses the
 * fused-wire codec (`primary_metric_desc`, `ended_at_asc`,
 * `optuna_trial_number_asc`) — the codec lives in
 * trials-table.column-config so the DataTable boundary stays generic.
 *
 * Removes the legacy `<Select>` sort control — column-header click sort
 * replaces it per FR-4 / AC-13.
 */
import { DataTable } from '@/components/common/data-table';
import { trialsColumns, trialsSortCodec } from '@/components/studies/trials-table.column-config';
import type { DataTableUrlStateApi } from '@/hooks/use-data-table-url-state';
import type { TrialDetail } from '@/lib/api/studies';

export interface TrialsTableProps {
  rows: readonly TrialDetail[];
  totalCount?: number;
  has_more: boolean;
  next_cursor: string | null;
  isLoading: boolean;
  isError: boolean;
  urlState: DataTableUrlStateApi;
}

export function TrialsTable({
  rows,
  totalCount,
  has_more,
  next_cursor,
  isLoading,
  isError,
  urlState,
}: TrialsTableProps) {
  return (
    <DataTable<TrialDetail>
      tableId="trials"
      tableTestId="trials-table"
      rowTestId={(r) => `trial-row-${r.id}`}
      columns={trialsColumns}
      data={rows}
      isLoading={isLoading}
      isError={isError}
      totalCount={totalCount}
      has_more={has_more}
      next_cursor={next_cursor}
      sort={urlState.sort}
      onSortChange={urlState.setSort}
      sortCodec={trialsSortCodec}
      cursor={urlState.cursor}
      pageSize={urlState.pageSize}
      onCursorChange={urlState.setCursor}
      onPageSizeChange={urlState.setPageSize}
      onClearMatchers={urlState.clearAllMatchers}
      anyMatcherActive={urlState.anyMatcherActive}
      emptyStateNoRows={{
        title: 'No trials yet',
        message: 'The study has not produced any trials.',
      }}
      emptyStateNoMatch={{ title: 'No trials match', message: '' }}
    />
  );
}
