// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

/**
 * Density toggle (feat_data_table_primitive Story 2.11 / FR-15).
 *
 * Two-position toggle: `comfortable` (default) / `compact`. The current
 * density is hoisted to DataTable so the cells can apply the matching
 * Tailwind class strings (`py-3 px-4` vs `py-1.5 px-3`).
 */

import { Button } from '@/components/ui/button';

export type DataTableDensity = 'comfortable' | 'compact';

export interface DataTableDensityToggleProps {
  density: DataTableDensity;
  onChange: (next: DataTableDensity) => void;
}

export function DataTableDensityToggle({ density, onChange }: DataTableDensityToggleProps) {
  return (
    <div
      className="inline-flex rounded-md border border-border"
      role="group"
      aria-label="Row density"
      data-testid="data-table-density-toggle"
    >
      <Button
        type="button"
        variant={density === 'comfortable' ? 'default' : 'ghost'}
        size="sm"
        className="rounded-r-none h-8"
        onClick={() => onChange('comfortable')}
        data-testid="data-table-density-toggle-comfortable"
        data-active={density === 'comfortable' ? 'true' : 'false'}
      >
        Comfortable
      </Button>
      <Button
        type="button"
        variant={density === 'compact' ? 'default' : 'ghost'}
        size="sm"
        className="rounded-l-none h-8"
        onClick={() => onChange('compact')}
        data-testid="data-table-density-toggle-compact"
        data-active={density === 'compact' ? 'true' : 'false'}
      >
        Compact
      </Button>
    </div>
  );
}
