// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Column configuration for `<JudgmentsTable>` (feat_data_table_primitive Story 3.6).
 *
 * 6 columns: Query (sticky, not sortable), Doc (not sortable), Rating
 * (sortable+tooltip, desc-first), Source (sortable+tooltip+filter enum),
 * Notes (not sortable), Actions (hideable=false, not sortable — renders
 * `<OverridePopover>` per row).
 *
 * Exported as `useJudgmentsColumns(listId)` because the actions column's
 * cell renderer closes over `listId` for `<OverridePopover listId={...}>`.
 *
 * `searchable={false}` per spec §3 — per-list judgments has no FTS.
 */
import { useMemo } from 'react';

import { StatusBadge } from '@/components/common/status-badge';
import type { DataTableColumnDef } from '@/components/common/types';
import { OverridePopover } from '@/components/judgments/override-popover';
import type { JudgmentRow } from '@/lib/api/judgments';
import { JUDGMENT_SOURCE_FILTER_VALUES } from '@/lib/enums';

export function useJudgmentsColumns(listId: string): DataTableColumnDef<JudgmentRow>[] {
  return useMemo(
    () => [
      {
        id: 'query_id',
        header: 'Query',
        accessorKey: 'query_id',
        sticky: true,
        cell: ({ row }) => <span className="font-mono text-xs">{row.original.query_id}</span>,
      },
      {
        id: 'doc_id',
        header: 'Doc',
        accessorKey: 'doc_id',
        cell: ({ row }) => <span className="font-mono text-xs">{row.original.doc_id}</span>,
      },
      {
        id: 'rating',
        header: 'Rating',
        accessorKey: 'rating',
        sortable: true,
        firstClickDirection: 'desc',
        tooltipKey: 'judgment.relevance',
        cell: ({ row }) => (
          <span data-testid={`judgment-rating-${row.original.id}`}>{row.original.rating}</span>
        ),
      },
      {
        id: 'source',
        header: 'Source',
        accessorKey: 'source',
        sortable: true,
        tooltipKey: 'judgment.source',
        filter: {
          kind: 'enum',
          wireValues: JUDGMENT_SOURCE_FILTER_VALUES,
          sourceOfTruth: 'backend/app/api/v1/schemas.py JudgmentSourceFilterWire',
        },
        cell: ({ row }) => (
          <span data-testid={`judgment-source-${row.original.id}`}>
            <StatusBadge kind="judgment_list" value={row.original.source} />
          </span>
        ),
      },
      {
        id: 'notes',
        header: 'Notes',
        accessorKey: 'notes',
        cell: ({ row }) => (
          <span data-testid={`judgment-notes-${row.original.id}`}>
            {row.original.notes ?? <span className="text-muted-foreground">—</span>}
          </span>
        ),
      },
      {
        id: 'actions',
        header: '',
        hideable: false,
        cell: ({ row }) => <OverridePopover listId={listId} judgment={row.original} />,
      },
    ],
    [listId],
  );
}
