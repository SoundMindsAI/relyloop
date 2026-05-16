/**
 * Column configuration for `<QuerySetsTable>` (feat_data_table_primitive Story 3.5).
 *
 * 3 columns: Name (link, sortable+sticky), Cluster, Created (sortable).
 * No filters. FTS on `name` (Story 1.2).
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
