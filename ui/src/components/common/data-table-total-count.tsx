// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

/**
 * Total-count display for `<DataTable>` (feat_data_table_primitive Story 2.5 / FR-7).
 *
 * Two display shapes per FR-7's cursor-paginator-honest design:
 *
 * - **First page** (cursor stack length 1 = no `?cursor=` in URL OR fresh
 *   in-app state): "Showing 1–<rowsRendered> of <totalCount>".
 *
 * - **Subsequent pages** (cursor stack length > 1 = user clicked Next at
 *   least once, OR direct URL load with `?cursor=<opaque>` — we can't
 *   distinguish): "Showing N rows (of M matching)". The absolute range
 *   `M–N` is intentionally omitted because the opaque cursor doesn't
 *   allow us to reconstruct the absolute page index on a fresh load.
 *
 * - `totalCount === 0`: "No matching rows".
 */

export interface DataTableTotalCountProps {
  /** From `X-Total-Count` header — passed through the consumer's hook. */
  totalCount: number;
  /** Number of rows currently visible on this page. */
  rowsRendered: number;
  /** 1 = first page; >1 = user navigated forward at least once. */
  cursorStackLength: number;
}

export function DataTableTotalCount({
  totalCount,
  rowsRendered,
  cursorStackLength,
}: DataTableTotalCountProps) {
  let text: string;
  if (totalCount === 0) {
    text = 'No matching rows';
  } else if (cursorStackLength <= 1) {
    text = `Showing 1–${rowsRendered.toLocaleString()} of ${totalCount.toLocaleString()}`;
  } else {
    text = `Showing ${rowsRendered.toLocaleString()} rows (of ${totalCount.toLocaleString()} matching)`;
  }
  return (
    <span className="text-xs text-muted-foreground" data-testid="data-table-total-count">
      {text}
    </span>
  );
}
