// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

/**
 * `<StudiesByClusterTable>` — per-cluster studies list
 * (feat_data_table_primitive Story 3.9 inheritance).
 *
 * Thin wrapper around `<StudiesTable>` scoped to a single `cluster_id`. The
 * URL state hook is namespaced to a different `tableId` ("studies-by-cluster")
 * so col-vis / density preferences don't bleed between the global
 * `/studies` page and per-cluster sub-views, but the user-facing behaviour
 * (search / sort / status filter / cursor pagination) inherits unchanged.
 *
 * `cluster_id` is fixed by the route — not encoded into URL filter state,
 * not surfaced as a filter chip.
 */
import { StudiesTable } from '@/components/studies/studies-table';
import { studiesColumns } from '@/components/studies/studies-table.column-config';
import { useDataTableUrlState } from '@/hooks/use-data-table-url-state';
import { useStudies } from '@/lib/api/studies';

export interface StudiesByClusterTableProps {
  clusterId: string;
}

export function StudiesByClusterTable({ clusterId }: StudiesByClusterTableProps) {
  const urlState = useDataTableUrlState('studies-by-cluster', studiesColumns, {
    defaultPageSize: 25,
  });
  const query = useStudies({
    cluster_id: clusterId,
    status: urlState.filters['status'],
    sort: urlState.sort ?? undefined,
    q: urlState.q ?? undefined,
    cursor: urlState.cursor ?? undefined,
    limit: urlState.pageSize,
  });
  return (
    <StudiesTable
      rows={query.data?.data ?? []}
      totalCount={query.data?.totalCount}
      has_more={query.data?.has_more ?? false}
      next_cursor={query.data?.next_cursor ?? null}
      isLoading={query.isPending}
      isError={query.isError}
      urlState={urlState}
    />
  );
}
