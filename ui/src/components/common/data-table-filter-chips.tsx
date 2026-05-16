'use client';

/**
 * Enum-filter chip row for `<DataTable>` (feat_data_table_primitive Story 2.3 / FR-5).
 *
 * Generalizes the existing `study-status-filter-chips.tsx` /
 * `proposal-status-filter-chips.tsx` / `proposal-source-filter-chips.tsx`
 * pattern. Renders one `<Button>` per wire value plus an "all" chip; clicking
 * calls `onChange(value | null)` (null on "all" or re-click).
 *
 * Disabled when `isLoading` so users don't fire filter changes mid-fetch.
 */

import { Button } from '@/components/ui/button';

const ALL = 'all' as const;

export interface DataTableFilterChipsProps {
  /** Column id — used in the `data-testid` so E2E specs can target it. */
  columnId: string;
  wireValues: readonly string[];
  /** Currently-active wire value (`null` = "all"). */
  value: string | null;
  onChange: (next: string | null) => void;
  /** Optional user-facing label override; defaults to the wire value verbatim. */
  label?: (value: string) => string;
  /** Disables clicks while the underlying query is fetching. */
  isLoading?: boolean;
  /** ARIA group label. */
  ariaLabel?: string;
}

export function DataTableFilterChips({
  columnId,
  wireValues,
  value,
  onChange,
  label,
  isLoading = false,
  ariaLabel,
}: DataTableFilterChipsProps) {
  const choices = [ALL, ...wireValues] as const;
  const active = value ?? ALL;
  return (
    <div
      className="flex flex-wrap items-center gap-2"
      role="group"
      aria-label={ariaLabel ?? `${columnId} filter`}
      data-testid={`filter-chips-${columnId}`}
    >
      {choices.map((choice) => {
        const isActive = choice === active;
        return (
          <Button
            key={choice}
            type="button"
            variant={isActive ? 'default' : 'outline'}
            size="sm"
            disabled={isLoading}
            data-testid={`filter-chip-${columnId}-${choice}`}
            data-active={isActive ? 'true' : 'false'}
            onClick={() => onChange(choice === ALL ? null : choice)}
          >
            {choice === ALL ? 'all' : label ? label(choice) : choice}
          </Button>
        );
      })}
    </div>
  );
}
