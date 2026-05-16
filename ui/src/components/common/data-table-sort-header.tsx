'use client';

/**
 * Sortable column-header sub-component for `<DataTable>`
 * (feat_data_table_primitive Story 2.2 / FR-4).
 *
 * Renders a clickable header button that cycles the column's sort state
 * `unsorted → <firstClickDirection> → <opposite> → unsorted`, with
 * a constraint for columns whose backend Literal only accepts a subset
 * of directions (e.g. trials' `optuna_trial_number_asc`-only — set
 * `sortDirections: ['asc']` on that column).
 *
 * Visual affordance: lucide-react chevrons (`ChevronUp` / `ChevronDown` /
 * `ChevronsUpDown` for the muted unsorted indicator).
 *
 * The component is presentation-only — it does NOT touch the URL. The
 * parent DataTable owns the `sort` prop + `onSortChange` callback; Story
 * 2.6 lifts those to a `useDataTableUrlState` hook at the consumer.
 *
 * ARIA: the `<th>` carries `aria-sort` (`ascending` / `descending` / `none`)
 * so screen readers announce the active state per spec §13 accessibility.
 */

import { ChevronDown, ChevronsUpDown, ChevronUp } from 'lucide-react';
import { useId } from 'react';

import { cn } from '@/lib/utils';

export type SortDir = 'asc' | 'desc';

export interface DataTableSortHeaderProps {
  label: React.ReactNode;
  /** Wire-form column name used in the `?sort=<col>:<dir>` URL/api value. */
  sortKey: string;
  /** Currently-active sort string from URL state (`null` when unsorted). */
  activeSort: string | null;
  /** Callback to commit the next sort value (or `null` to clear). */
  onSortChange: (next: string | null) => void;
  /** First-click direction (default `'asc'`). */
  firstClickDirection?: SortDir;
  /** Constrain the cycle (default `['asc', 'desc']`). */
  sortDirections?: readonly SortDir[];
  /** Optional tooltip slot (Story 2.8 renders `<InfoTooltip>` next to label). */
  trailing?: React.ReactNode;
}

function currentDir(activeSort: string | null, sortKey: string): SortDir | null {
  if (!activeSort) return null;
  const [col, dir] = activeSort.split(':');
  if (col !== sortKey) return null;
  return dir === 'asc' || dir === 'desc' ? dir : null;
}

/**
 * Three-state cycle, with `sortDirections` constraint.
 *
 * Default (`['asc', 'desc']`):  unsorted → first → opposite → unsorted
 * `['asc']` only:               unsorted → asc → unsorted
 * `['desc']` only:              unsorted → desc → unsorted
 *
 * The cycle is exactly 3 visible states. After reaching the second (opposite)
 * direction, the third click clears to null — does NOT ping-pong back to the
 * first direction. This matches the FR-4 spec wording verbatim.
 */
export function nextSortValue(
  current: SortDir | null,
  sortKey: string,
  firstClickDirection: SortDir,
  sortDirections: readonly SortDir[],
): string | null {
  // Click 1 (current === null): go to firstClickDirection if it's allowed;
  // otherwise to the only allowed direction (handles sortDirections=['desc']
  // with firstClickDirection='asc' as a fail-soft case).
  if (current === null) {
    const target = sortDirections.includes(firstClickDirection)
      ? firstClickDirection
      : sortDirections[0];
    return target === undefined ? null : `${sortKey}:${target}`;
  }

  // Click 2 (current === firstClickDirection): advance to the opposite
  // direction IF it's allowed by sortDirections, else clear to null.
  if (current === firstClickDirection) {
    const opposite: SortDir = current === 'asc' ? 'desc' : 'asc';
    if (sortDirections.includes(opposite)) {
      return `${sortKey}:${opposite}`;
    }
    return null;
  }

  // Click 3 (current is the opposite direction): always clear to null.
  return null;
}

export function DataTableSortHeader({
  label,
  sortKey,
  activeSort,
  onSortChange,
  firstClickDirection = 'asc',
  sortDirections = ['asc', 'desc'],
  trailing,
}: DataTableSortHeaderProps) {
  const dir = currentDir(activeSort, sortKey);
  const buttonId = useId();
  const ariaSort = dir === 'asc' ? 'ascending' : dir === 'desc' ? 'descending' : 'none';
  const Chevron = dir === 'asc' ? ChevronUp : dir === 'desc' ? ChevronDown : ChevronsUpDown;
  const chevronClass = dir === null ? 'opacity-40' : '';

  const handleClick = () => {
    onSortChange(nextSortValue(dir, sortKey, firstClickDirection, sortDirections));
  };

  return (
    <span aria-sort={ariaSort} className="inline-flex items-center gap-1">
      <button
        id={buttonId}
        type="button"
        onClick={handleClick}
        className={cn(
          'inline-flex items-center gap-1 text-left',
          'hover:text-foreground focus-visible:outline-none focus-visible:ring-2',
          'focus-visible:ring-ring focus-visible:rounded-sm',
        )}
        data-testid={`data-table-sort-${sortKey}`}
        data-active-dir={dir ?? 'none'}
      >
        <span>{label}</span>
        <Chevron className={cn('h-3.5 w-3.5', chevronClass)} aria-hidden="true" />
        <span className="sr-only">
          {dir === 'asc' ? 'Sorted ascending' : dir === 'desc' ? 'Sorted descending' : 'Not sorted'}
        </span>
      </button>
      {trailing}
    </span>
  );
}
