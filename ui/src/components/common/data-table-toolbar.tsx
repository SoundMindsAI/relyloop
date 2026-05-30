// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

/**
 * Toolbar slot rendered above the table body.
 *
 * Story 2.1 scaffold — renders nothing visible by default. Subsequent stories
 * populate it:
 *   - 2.3: enum filter chip rows + fk-select dropdowns
 *   - 2.4: debounced text-search input
 *   - 2.5: total-count display
 *   - 2.10: column visibility menu (eye icon)
 *   - 2.11: density toggle (comfortable / compact)
 *
 * Props mirror what `<DataTable>` will hand down. Optional fields keep the
 * type-check green while the scaffold is being incrementally built.
 */

import type * as React from 'react';

export interface DataTableToolbarProps {
  tableId: string;
  /** Marker used by E2E specs to assert toolbar mount. */
  testid?: string;
  /** Slot rendered on the left (filters + search land here in later stories). */
  leftSlot?: React.ReactNode;
  /** Slot rendered on the right (total count + density + col-vis later). */
  rightSlot?: React.ReactNode;
}

export function DataTableToolbar({
  testid = 'data-table-toolbar',
  leftSlot = null,
  rightSlot = null,
}: DataTableToolbarProps) {
  if (leftSlot === null && rightSlot === null) {
    // Scaffold default: no toolbar elements yet — render nothing visible.
    // The testid still attaches so E2E specs from Epic 3 can locate it.
    return <div data-testid={testid} className="hidden" />;
  }
  return (
    <div data-testid={testid} className="flex flex-wrap items-center justify-between gap-3 pb-3">
      <div className="flex flex-wrap items-center gap-2">{leftSlot}</div>
      <div className="flex flex-wrap items-center gap-2">{rightSlot}</div>
    </div>
  );
}
