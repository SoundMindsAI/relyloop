// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

/**
 * Bulk-action toolbar for `<DataTable>` (feat_data_table_primitive Story 2.9 / FR-13).
 *
 * Renders ABOVE the table body when `selectedCount >= 1`. Shows a counter
 * ("N selected on this page" per FR-13) plus consumer-supplied action
 * buttons. Each action receives `(selectedIds, clearSelection)`.
 */

import type { BulkAction } from './types';

import { Button } from '@/components/ui/button';

export interface DataTableBulkActionsProps {
  selectedIds: readonly string[];
  actions: readonly BulkAction[];
  onClear: () => void;
}

export function DataTableBulkActions({ selectedIds, actions, onClear }: DataTableBulkActionsProps) {
  const count = selectedIds.length;
  if (count === 0) return null;
  return (
    <div
      className="flex items-center justify-between rounded-md border border-border bg-muted/40 px-3 py-2"
      data-testid="data-table-bulk-actions"
    >
      <span className="text-sm">
        <span data-testid="data-table-bulk-actions-count">{count}</span> selected on this page
      </span>
      <div className="flex items-center gap-2">
        {actions.map((action, idx) => (
          <Button
            key={action.testid ?? `${action.label}-${idx}`}
            type="button"
            variant={action.variant === 'destructive' ? 'destructive' : 'default'}
            size="sm"
            data-testid={action.testid ?? `data-table-bulk-action-${idx}`}
            onClick={() => action.onClick([...selectedIds], onClear)}
          >
            {action.label}
          </Button>
        ))}
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={onClear}
          data-testid="data-table-bulk-actions-clear"
        >
          Clear
        </Button>
      </div>
    </div>
  );
}
