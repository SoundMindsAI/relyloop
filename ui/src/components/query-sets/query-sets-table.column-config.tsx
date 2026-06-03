// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Column configuration for `<QuerySetsTable>` (feat_data_table_primitive Story 3.5).
 *
 * 4 columns: Name (link, sortable+sticky), Cluster, Queries (count), Created
 * (sortable). No filters. FTS on `name` (Story 1.2). The Queries column reads
 * the `query_count` field added to `QuerySetSummary` by feat_list_count_columns
 * (resolved server-side via one batched aggregate per page — no N+1).
 */
import Link from 'next/link';

import type { DataTableColumnDef } from '@/components/common/types';
import type { QuerySetSummary } from '@/lib/api/query-sets';

export const querySetsColumns: DataTableColumnDef<QuerySetSummary>[] = [
  {
    id: 'name',
    header: 'Name',
    accessorKey: 'name',
    sortable: true,
    sticky: true,
    cell: ({ row }) => (
      <Link
        href={`/query-sets/${row.original.id}`}
        className="text-blue-600 underline-offset-4 hover:underline"
      >
        {row.original.name}
      </Link>
    ),
  },
  {
    id: 'cluster_id',
    header: 'Cluster',
    accessorKey: 'cluster_id',
    cell: ({ row }) => <span className="font-mono text-xs">{row.original.cluster_id}</span>,
  },
  {
    id: 'query_count',
    header: 'Queries',
    accessorKey: 'query_count',
    cell: ({ row }) => (
      <span className="tabular-nums">{row.original.query_count.toLocaleString()}</span>
    ),
  },
  {
    id: 'created_at',
    header: 'Created',
    accessorKey: 'created_at',
    sortable: true,
    firstClickDirection: 'desc',
    cell: ({ row }) => (
      <span className="whitespace-nowrap">
        {new Date(row.original.created_at).toLocaleString()}
      </span>
    ),
  },
];
