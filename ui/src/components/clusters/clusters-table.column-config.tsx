/**
 * Column configuration for `<ClustersTable>` (feat_data_table_primitive Story 3.3).
 *
 * 6 columns (5 visible by default, Created hideable): Name (link,
 * sortable+sticky), Engine (filter enum), Environment (sortable, filter
 * enum), Health (synthetic — not sortable / not filterable), Base URL,
 * Created (sortable, hideable so the original 5-column layout is the
 * default but the user can opt in to a created-at sort+view).
 *
 * Filters wire to the new backend `?engine_type=` and `?environment=` params
 * (Story 1.4) and `?q=` FTS on `name + base_url` (Story 1.2).
 */
import Link from 'next/link';

import { StatusBadge } from '@/components/common/status-badge';
import type { DataTableColumnDef } from '@/components/common/types';
import type { ClusterSummary } from '@/lib/api/clusters';
import { ENGINE_TYPE_VALUES, ENVIRONMENT_VALUES } from '@/lib/enums';

export const clustersColumns: DataTableColumnDef<ClusterSummary>[] = [
  {
    id: 'name',
    header: 'Name',
    accessorKey: 'name',
    sortable: true,
    sticky: true,
    cell: ({ row }) => (
      <Link
        href={`/clusters/${row.original.id}`}
        className="text-blue-600 underline-offset-4 hover:underline"
      >
        {row.original.name}
      </Link>
    ),
  },
  {
    id: 'engine_type',
    header: 'Engine',
    accessorKey: 'engine_type',
    filter: {
      kind: 'enum',
      wireValues: ENGINE_TYPE_VALUES,
      sourceOfTruth: 'backend/app/api/v1/schemas.py EngineTypeWire',
    },
  },
  {
    id: 'environment',
    header: 'Environment',
    accessorKey: 'environment',
    sortable: true,
    filter: {
      kind: 'enum',
      wireValues: ENVIRONMENT_VALUES,
      sourceOfTruth: 'backend/app/api/v1/schemas.py Environment',
    },
  },
  {
    id: 'health',
    header: 'Health',
    // Synthetic field — not on the row directly; rendered from health_check.status.
    cell: ({ row }) => <StatusBadge kind="health" value={row.original.health_check.status} />,
  },
  {
    id: 'base_url',
    header: 'Base URL',
    accessorKey: 'base_url',
    cell: ({ row }) => <span className="font-mono text-xs">{row.original.base_url}</span>,
  },
  {
    id: 'created_at',
    header: 'Created',
    accessorKey: 'created_at',
    sortable: true,
    firstClickDirection: 'desc',
    hideable: true,
    cell: ({ row }) => (
      <span className="whitespace-nowrap">
        {new Date(row.original.created_at).toLocaleString()}
      </span>
    ),
  },
];
