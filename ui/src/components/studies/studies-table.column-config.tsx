/**
 * Column configuration for `<StudiesTable>` (feat_data_table_primitive Story 3.1).
 *
 * Six columns mirroring the legacy studies-table.tsx layout, lifted into a
 * declarative TanStack ColumnDef array consumed by the shared `<DataTable>`
 * primitive. The `status` filter is the planned migration target of the
 * deleted `<StudyStatusFilterChips>` — wire values are sourced from
 * `STUDY_STATUS_VALUES` in `@/lib/enums` (which itself carries the canonical
 * `// Values must match backend/app/api/v1/schemas.py StudyStatusWire`
 * source-of-truth comment per the Story 2.13 lint guard).
 */
import Link from 'next/link';

import { StatusBadge } from '@/components/common/status-badge';
import type { DataTableColumnDef } from '@/components/common/types';
import type { StudySummary } from '@/lib/api/studies';
import { STUDY_STATUS_VALUES } from '@/lib/enums';

export const studiesColumns: DataTableColumnDef<StudySummary>[] = [
  {
    id: 'name',
    header: 'Name',
    accessorKey: 'name',
    sortable: true,
    cell: ({ row }) => (
      <Link
        href={`/studies/${row.original.id}`}
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
    sticky: true,
    // Plan Story 3.1: cluster_id is not hideable. sticky force-shows in
    // render; hideable: false also hides it from the col-vis menu.
    hideable: false,
    cell: ({ row }) => <span className="font-mono text-xs">{row.original.cluster_id}</span>,
  },
  {
    id: 'status',
    header: 'Status',
    accessorKey: 'status',
    sortable: true,
    filter: {
      kind: 'enum',
      wireValues: STUDY_STATUS_VALUES,
      sourceOfTruth: 'backend/app/api/v1/schemas.py StudyStatusWire',
    },
    cell: ({ row }) => <StatusBadge kind="study" value={row.original.status} />,
  },
  {
    id: 'best_metric',
    header: 'Best metric',
    accessorKey: 'best_metric',
    sortable: true,
    firstClickDirection: 'desc',
    cell: ({ row }) =>
      row.original.best_metric != null ? (
        row.original.best_metric.toFixed(3)
      ) : (
        <span className="text-muted-foreground">—</span>
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
  {
    id: 'completed_at',
    header: 'Completed',
    accessorKey: 'completed_at',
    sortable: true,
    hideable: true,
    cell: ({ row }) =>
      row.original.completed_at ? (
        <span className="whitespace-nowrap">
          {new Date(row.original.completed_at).toLocaleString()}
        </span>
      ) : (
        <span className="text-muted-foreground">—</span>
      ),
  },
];
