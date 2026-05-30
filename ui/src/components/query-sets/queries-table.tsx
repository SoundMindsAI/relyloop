// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

/**
 * `<QueriesTable>` thin DataTable consumer
 * (feat_data_table_primitive Story 3.8).
 *
 * The per-query sub-resource has no FTS, no sort, and no bulk actions —
 * searchable=false, selectable=false. Page-size options are
 * `[10, 25, 50, 100]` per the legacy parity table; URL-state owned by
 * useDataTableUrlState scoped to a per-query-set tableId so different
 * query sets keep distinct col-vis + density preferences.
 *
 * The page hosts the EditMetadataDialog and the column config calls back
 * into the table to open it (the cell renderers close over the opener).
 */
import { useCallback, useState } from 'react';

import { DataTable } from '@/components/common/data-table';
import { EmptyState } from '@/components/common/empty-state';
import { useDataTableUrlState } from '@/hooks/use-data-table-url-state';
import { type QueryRow, useQueries } from '@/lib/api/query-sets';

import { EditMetadataDialog } from './edit-metadata-dialog';
import { useQueriesColumns } from './queries-table.column-config';

const PAGE_SIZE_OPTIONS = [10, 25, 50, 100] as const;

export interface QueriesTableProps {
  querySetId: string;
}

export function QueriesTable({ querySetId }: QueriesTableProps) {
  const [metadataQuery, setMetadataQuery] = useState<QueryRow | null>(null);
  const openMetadata = useCallback((row: QueryRow) => setMetadataQuery(row), []);
  const columns = useQueriesColumns(querySetId, openMetadata);
  // Namespace the URL hook per query-set so col-vis / density don't bleed
  // across `/query-sets/<a>` and `/query-sets/<b>` pages.
  const urlState = useDataTableUrlState(`queries-${querySetId}`, columns, {
    defaultPageSize: 50,
    pageSizeOptions: PAGE_SIZE_OPTIONS,
  });
  const queries = useQueries(querySetId, {
    cursor: urlState.cursor ?? undefined,
    limit: urlState.pageSize,
  });

  // Preserve the legacy error placeholder — the DataTable's generic error
  // empty-state is fine, but the parent surface relies on a distinct
  // copy for this resource per Story 3.8 parity row 8.
  if (queries.isError) {
    return <EmptyState title="Failed to load queries" message="Try again or check the backend." />;
  }

  return (
    <>
      <DataTable<QueryRow>
        tableId={`queries-${querySetId}`}
        tableTestId="queries-table"
        rowTestId={(r) => `row-${r.id}`}
        columns={columns}
        data={queries.data?.data ?? []}
        isLoading={queries.isPending}
        isError={false}
        totalCount={queries.data?.totalCount}
        has_more={queries.data?.has_more ?? false}
        next_cursor={queries.data?.next_cursor ?? null}
        cursor={urlState.cursor}
        pageSize={urlState.pageSize}
        onCursorChange={urlState.setCursor}
        onPageSizeChange={urlState.setPageSize}
        pageSizeOptions={PAGE_SIZE_OPTIONS}
        onClearMatchers={urlState.clearAllMatchers}
        anyMatcherActive={urlState.anyMatcherActive}
        emptyStateNoRows={{
          title: 'No queries yet',
          message: 'Use Add queries above to bulk-upload JSON or CSV.',
        }}
      />
      {metadataQuery && (
        <EditMetadataDialog
          querySetId={querySetId}
          query={metadataQuery}
          open={metadataQuery !== null}
          onOpenChange={(open) => {
            if (!open) setMetadataQuery(null);
          }}
        />
      )}
    </>
  );
}
