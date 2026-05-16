/**
 * Column configuration for `<TemplatesTable>` (feat_data_table_primitive Story 3.4).
 *
 * 4 columns: Name (link, sortable+sticky), Engine (sortable, filter enum),
 * Version (sortable), Created (sortable, hideable). FTS on `name` (Story 1.2).
 */
import Link from 'next/link';

import type { DataTableColumnDef } from '@/components/common/types';
import type { QueryTemplateSummary } from '@/lib/api/query-templates';
import { ENGINE_TYPE_VALUES } from '@/lib/enums';

export const templatesColumns: DataTableColumnDef<QueryTemplateSummary>[] = [
  {
    id: 'name',
    header: 'Name',
    accessorKey: 'name',
    sortable: true,
    sticky: true,
    cell: ({ row }) => (
      <Link
        href={`/templates/${row.original.id}`}
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
    sortable: true,
    filter: {
      kind: 'enum',
      wireValues: ENGINE_TYPE_VALUES,
      sourceOfTruth: 'backend/app/api/v1/schemas.py EngineTypeWire',
    },
  },
  {
    id: 'version',
    header: 'Version',
    accessorKey: 'version',
    sortable: true,
    firstClickDirection: 'desc',
    cell: ({ row }) => `v${row.original.version}`,
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
