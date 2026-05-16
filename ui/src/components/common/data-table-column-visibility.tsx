'use client';

/**
 * Column-visibility menu (feat_data_table_primitive Story 2.10 / FR-14).
 *
 * Uses the existing shadcn `<Popover>` primitive (no new Radix dep) and
 * native `<input type="checkbox">` per the plan's "no @radix-ui/react-dropdown-menu"
 * decision. Sticky columns are excluded from the menu (the selection
 * checkbox + first identifier column stay visible at all times per FR-14).
 */

import { Eye } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';

export interface ColumnVisibilityItem {
  id: string;
  label: string;
  /** When `true`, the column is hidden by user choice. */
  hidden: boolean;
  /** When `true`, the column is sticky and not appears in the menu. */
  sticky?: boolean;
}

export interface DataTableColumnVisibilityProps {
  items: readonly ColumnVisibilityItem[];
  onToggle: (id: string) => void;
}

export function DataTableColumnVisibility({ items, onToggle }: DataTableColumnVisibilityProps) {
  const hideable = items.filter((item) => !item.sticky);
  if (hideable.length === 0) return null;
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-8 gap-1"
          data-testid="data-table-column-visibility"
          aria-label="Show or hide columns"
        >
          <Eye className="h-4 w-4" aria-hidden="true" />
          <span className="sr-only">Columns</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-56 p-2">
        <p className="px-2 py-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Columns
        </p>
        <div className="space-y-1">
          {hideable.map((item) => (
            <label
              key={item.id}
              className="flex cursor-pointer items-center gap-2 rounded-sm px-2 py-1 text-sm hover:bg-muted"
              data-testid={`data-table-column-visibility-row-${item.id}`}
            >
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-border accent-primary"
                checked={!item.hidden}
                onChange={() => onToggle(item.id)}
                data-testid={`data-table-column-visibility-toggle-${item.id}`}
              />
              {item.label}
            </label>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}
