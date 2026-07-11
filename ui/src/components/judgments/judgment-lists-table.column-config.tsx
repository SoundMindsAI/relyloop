// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Column configuration for `<JudgmentListsTable>` — the /judgments index.
 *
 * 4 columns: Name (link to detail), Status, Target, Created. No sort/filter —
 * the `useJudgmentLists` hook is cursor/limit only (no `?sort=`/`?q=`), so
 * these are display columns. No enum filters → no `sourceOfTruth` required by
 * the column-config-discipline test.
 */
import Link from 'next/link';

import { StatusBadge } from '@/components/common/status-badge';
import type { DataTableColumnDef } from '@/components/common/types';
import type { JudgmentListSummary } from '@/lib/api/judgments';

export const judgmentListsColumns: DataTableColumnDef<JudgmentListSummary>[] = [
  {
    id: 'name',
    header: 'Name',
    accessorKey: 'name',
    sticky: true,
    cell: ({ row }) => (
      <Link
        href={`/judgments/${row.original.id}`}
        className="text-blue-600 underline-offset-4 hover:underline"
      >
        {row.original.name}
      </Link>
    ),
  },
  {
    id: 'status',
    header: 'Status',
    accessorKey: 'status',
    cell: ({ row }) => <StatusBadge kind="judgment_list" value={row.original.status} />,
  },
  {
    id: 'target',
    header: 'Target',
    accessorKey: 'target',
    cell: ({ row }) => <span className="font-mono text-xs">{row.original.target}</span>,
  },
  {
    id: 'created_at',
    header: 'Created',
    accessorKey: 'created_at',
    cell: ({ row }) => (
      <span className="whitespace-nowrap">
        {new Date(row.original.created_at).toLocaleString()}
      </span>
    ),
  },
];
