// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Column configuration for `<QueriesTable>` (feat_data_table_primitive Story 3.8).
 *
 * 5 columns: Query text (sticky, not sortable, truncated 100ch), Reference
 * answer (hideable, truncated 50ch), Metadata (Badge, opens
 * EditMetadataDialog), Judgments count (not sortable — the per-query
 * sub-resource has no ?sort= support), Actions (hideable=false,
 * sortable=false — renders the 3 per-row popovers/dialogs).
 *
 * searchable=false and selectable=false per spec — the per-query endpoint
 * has no FTS and no bulk actions in scope.
 *
 * Exported as `useQueriesColumns(...)` because the action-column cell
 * renderers close over `querySetId` and the metadata-dialog opener.
 */
import { useMemo } from 'react';

import type { DataTableColumnDef } from '@/components/common/types';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import type { QueryRow } from '@/lib/api/query-sets';

import { DeleteQueryDialog } from './delete-query-dialog';
import { EditQueryPopover } from './edit-query-popover';

function truncate(s: string, max: number): string {
  return s.length > max ? s.slice(0, max - 1) + '…' : s;
}

export function useQueriesColumns(
  querySetId: string,
  onOpenMetadata: (row: QueryRow) => void,
): DataTableColumnDef<QueryRow>[] {
  return useMemo(
    () => [
      {
        id: 'query_text',
        header: 'Query text',
        accessorKey: 'query_text',
        sticky: true,
        cell: ({ row }) => (
          <span className="max-w-md" title={row.original.query_text}>
            {truncate(row.original.query_text, 100)}
          </span>
        ),
      },
      {
        id: 'reference_answer',
        header: 'Reference answer',
        accessorKey: 'reference_answer',
        hideable: true,
        cell: ({ row }) => {
          const ra = row.original.reference_answer;
          return (
            <span className="max-w-xs" title={ra ?? 'Reference answer not set'}>
              {ra === null ? '—' : truncate(ra, 50)}
            </span>
          );
        },
      },
      {
        id: 'query_metadata',
        header: 'Metadata',
        cell: ({ row }) => (
          <Badge
            variant={row.original.query_metadata ? 'default' : 'secondary'}
            role="button"
            tabIndex={0}
            aria-label={
              row.original.query_metadata
                ? 'Edit query metadata (set)'
                : 'Edit query metadata (not set)'
            }
            onClick={() => onOpenMetadata(row.original)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onOpenMetadata(row.original);
              }
            }}
            className="cursor-pointer focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none"
            data-testid={`meta-badge-${row.original.id}`}
          >
            {row.original.query_metadata ? 'Set' : '—'}
          </Badge>
        ),
      },
      {
        id: 'judgment_count',
        header: 'Judgments',
        accessorKey: 'judgment_count',
        cell: ({ row }) => (
          <span className="text-right">{row.original.judgment_count.toLocaleString()}</span>
        ),
      },
      {
        id: 'actions',
        header: '',
        hideable: false,
        cell: ({ row }) => (
          <div className="flex justify-end gap-1">
            <EditQueryPopover
              querySetId={querySetId}
              query={row.original}
              trigger={
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label="Edit query"
                  title="Edit query text and reference answer"
                  data-testid={`edit-${row.original.id}`}
                >
                  ✏️
                </Button>
              }
            />
            <Button
              variant="ghost"
              size="icon"
              onClick={() => onOpenMetadata(row.original)}
              aria-label="Edit query metadata"
              title="Edit query metadata"
              data-testid={`meta-${row.original.id}`}
            >
              {'{ }'}
            </Button>
            <DeleteQueryDialog
              querySetId={querySetId}
              query={row.original}
              trigger={
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label="Delete query"
                  title={
                    row.original.judgment_count > 0
                      ? `Delete blocked — query has ${row.original.judgment_count} judgment(s). Remove the parent judgment list first.`
                      : 'Delete query'
                  }
                  className="text-destructive"
                  data-testid={`delete-${row.original.id}`}
                >
                  🗑
                </Button>
              }
            />
          </div>
        ),
      },
    ],
    [querySetId, onOpenMetadata],
  );
}
