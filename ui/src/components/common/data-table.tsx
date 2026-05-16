'use client';

/**
 * `<DataTable>` — shared table primitive (feat_data_table_primitive Epic 2).
 *
 * Story 2.1 scaffold: renders rows from `props.data` using TanStack Table's
 * row model + the existing shadcn `<Table>` primitive. Loading and error
 * states are mapped to single-line placeholders so consumers can already
 * pass `query.isPending` / `query.isError` through without conditional
 * branching at the call site.
 *
 * The empty-state branching (Story 2.7), sort cycle (Story 2.2), filters
 * (Story 2.3), search input (Story 2.4), total-count (Story 2.5), URL state
 * (Story 2.6), sticky header + tooltips (Story 2.8), selection (Story 2.9),
 * column visibility (Story 2.10), density (Story 2.11), and keyboard nav
 * (Story 2.12) all layer onto this shell. The shell deliberately ships with
 * the toolbar slot wired but empty so future stories only need to populate
 * it; no consumer rework when each layer lands.
 */

import { flexRender, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import { useEffect, useRef, useState, type KeyboardEvent } from 'react';

import { CursorPaginator } from '@/components/common/cursor-paginator';
import { InfoTooltip } from '@/components/common/info-tooltip';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

import { useLocalStorageSet } from '@/hooks/use-local-storage-set';

import { DataTableBulkActions } from './data-table-bulk-actions';
import { DataTableColumnVisibility } from './data-table-column-visibility';
import { type DataTableDensity, DataTableDensityToggle } from './data-table-density-toggle';
import { DataTableEmpty } from './data-table-empty';
import { DataTableFilterChips } from './data-table-filter-chips';
import { DataTableFkSelect } from './data-table-fk-select';
import { DataTableSearch } from './data-table-search';
import { DataTableSortHeader } from './data-table-sort-header';
import { DataTableToolbar } from './data-table-toolbar';
import { DataTableTotalCount } from './data-table-total-count';
import type { DataTableColumnDef, DataTableProps } from './types';

export function DataTable<T extends { id: string }>(props: DataTableProps<T>) {
  const {
    columns,
    data,
    isLoading,
    isError,
    emptyStateNoRows,
    tableTestId,
    rowTestId,
    sort = null,
    onSortChange,
    filters,
    onFilterChange,
    q = null,
    onQChange,
    searchable = false,
    totalCount,
    cursor = null,
    pageSize = 50,
    onCursorChange,
    onPageSizeChange,
    pageSizeOptions,
    onClearMatchers,
    anyMatcherActive = false,
    has_more,
    next_cursor,
    selectable = false,
    bulkActions,
    onSelectionChange,
    keyboardNav = true,
    onRowActivate,
  } = props;

  // Story 2.5 / 2.7 — cursor stack: DataTable owns the trail of cursors the
  // user has clicked Next through, so Prev can step back one page instead
  // of always returning to page 1. Stack entry [0] is always `null` (first
  // page); each Next click pushes the current `next_cursor`. The stack is
  // re-grounded whenever the URL `cursor` changes externally (filter / sort /
  // q change, shared-link hydration) so it never drifts out of sync.
  const [cursorStack, setCursorStack] = useState<(string | null)[]>(() => [cursor ?? null]);
  useEffect(() => {
    setCursorStack((prev) => {
      const last = prev[prev.length - 1] ?? null;
      if (last === (cursor ?? null)) return prev;
      // Cursor changed externally (filter/sort/q reset, hydration). Reset
      // the stack to a single entry — we no longer know the user's trail.
      return [cursor ?? null];
    });
  }, [cursor]);
  // A direct load of `?cursor=<opaque>` initializes the stack to length 1
  // (we don't know the trail), but the user is *not* on page 1. Treat any
  // non-null cursor as a subsequent page for the FR-7 cursor-paginator-honest
  // wording, regardless of stack length.
  const cursorStackLength = cursor ? Math.max(cursorStack.length, 2) : cursorStack.length;
  const goNext = () => {
    if (!has_more || !next_cursor || !onCursorChange) return;
    setCursorStack((prev) => [...prev, next_cursor]);
    onCursorChange(next_cursor);
  };
  const goPrev = () => {
    if (!onCursorChange || cursorStack.length <= 1) return;
    const nextStack = cursorStack.slice(0, -1);
    setCursorStack(nextStack);
    onCursorChange(nextStack[nextStack.length - 1] ?? null);
  };

  // Story 2.10 — column visibility persisted to localStorage per tableId.
  const hiddenColumns = useLocalStorageSet(`relyloop:datatable:${props.tableId}:hidden-columns`);
  // Story 2.11 — density persisted to localStorage per tableId.
  const densityKey = `relyloop:datatable:${props.tableId}:density`;
  const [density, setDensityState] = useState<DataTableDensity>('comfortable');
  useEffect(() => {
    try {
      const raw = typeof window !== 'undefined' ? window.localStorage.getItem(densityKey) : null;
      if (raw === 'compact' || raw === 'comfortable') setDensityState(raw);
    } catch {
      /* private-browsing fallback */
    }
  }, [densityKey]);
  const setDensity = (next: DataTableDensity) => {
    setDensityState(next);
    try {
      if (typeof window !== 'undefined') window.localStorage.setItem(densityKey, next);
    } catch {
      /* swallow */
    }
  };
  // Density Tailwind classes applied to cells (header + body).
  const cellPaddingClass = density === 'compact' ? 'py-1.5 px-3' : 'py-3 px-4';

  // Story 2.9 — selection state (React-only, never URL-encoded per spec FR-13).
  // Cleared on cursor / filter / sort / q change via the effect below.
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  // Build a stable key from the URL-state pieces — selection clears whenever
  // any of these change so a moved cursor or filter flip doesn't leave a
  // stale per-row selection visible across pages.
  const urlStateKey = JSON.stringify({ cursor, sort, q, filters });
  useEffect(() => {
    setSelectedIds(new Set());
  }, [urlStateKey]);
  useEffect(() => {
    onSelectionChange?.(Array.from(selectedIds));
  }, [selectedIds, onSelectionChange]);

  const toggleRow = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };
  const toggleAllOnPage = () => {
    setSelectedIds((prev) => {
      const allOnPage = data.every((r) => prev.has(r.id));
      if (allOnPage) {
        // Currently all selected on page → unselect all on page.
        const next = new Set(prev);
        data.forEach((r) => next.delete(r.id));
        return next;
      }
      // Some/none selected on page → select all on page.
      const next = new Set(prev);
      data.forEach((r) => next.add(r.id));
      return next;
    });
  };
  const clearSelection = () => setSelectedIds(new Set());

  const allOnPageSelected = data.length > 0 && data.every((r) => selectedIds.has(r.id));
  const someOnPageSelected =
    data.length > 0 && data.some((r) => selectedIds.has(r.id)) && !allOnPageSelected;

  // Story 2.12 — keyboard navigation (FR-16). Roving tabindex: only the
  // currently-focused row is in the tab order; Arrow Up/Down move focus
  // (wrapping at ends), Enter activates the row, Space toggles selection
  // when `selectable`. Disabled entirely when `keyboardNav === false`.
  const [focusedRowIndex, setFocusedRowIndex] = useState(0);
  const rowRefs = useRef<Array<HTMLTableRowElement | null>>([]);
  // Clamp the focused index back into bounds when data length shrinks
  // (filters, cursor moves) so we never point past the last row.
  useEffect(() => {
    if (focusedRowIndex > 0 && focusedRowIndex >= data.length) {
      setFocusedRowIndex(Math.max(0, data.length - 1));
    }
  }, [data.length, focusedRowIndex]);
  const handleRowKeyDown = (event: KeyboardEvent<HTMLTableRowElement>, idx: number) => {
    if (!keyboardNav || data.length === 0) return;
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      const next = (idx + 1) % data.length;
      setFocusedRowIndex(next);
      rowRefs.current[next]?.focus();
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      const next = (idx - 1 + data.length) % data.length;
      setFocusedRowIndex(next);
      rowRefs.current[next]?.focus();
    } else if (event.key === 'Enter') {
      event.preventDefault();
      const row = data[idx];
      if (row && onRowActivate) onRowActivate(row.id);
    } else if (event.key === ' ' && selectable) {
      // Space toggles selection — matches the checkbox the row already renders.
      event.preventDefault();
      const row = data[idx];
      if (row) toggleRow(row.id);
    }
  };

  // Build the filter slot for the toolbar (Story 2.3 / FR-5).
  // Each filterable column gets a chip row (enum) or `<select>` (fk-select).
  const filterSlot = onFilterChange
    ? columns.flatMap((col) => {
        if (!col.filter) return [];
        if (col.filter.kind === 'enum') {
          return [
            <DataTableFilterChips
              key={col.id}
              columnId={col.id}
              wireValues={col.filter.wireValues}
              value={filters?.[col.id] ?? null}
              onChange={(next) => onFilterChange(col.id, next)}
              isLoading={isLoading}
              label={col.filter.label}
            />,
          ];
        }
        // kind === 'fk-select'
        return [
          <DataTableFkSelect
            key={col.id}
            columnId={col.id}
            useOptions={col.filter.useOptions}
            value={filters?.[col.id] ?? null}
            onChange={(next) => onFilterChange(col.id, next)}
            placeholder={col.filter.placeholder}
            isLoading={isLoading}
          />,
        ];
      })
    : [];

  // TanStack Table model. `getRowId: (row) => row.id` keys row identity on the
  // backend UUID rather than the row index — required for stable selection,
  // keyboard activation, and per-row testids when rows shift across pages.
  // Story 2.10 — column visibility state derived from the localStorage set.
  // Non-hideable columns (sticky OR hideable === false) are force-shown even
  // if a tampered localStorage entry tries to hide them.
  const visibleColumns = columns.filter(
    (c) => c.sticky || c.hideable === false || !hiddenColumns.has(c.id),
  );
  const table = useReactTable<T>({
    data: data as T[],
    // TanStack Table's `columns` prop is typed as a mutable `ColumnDef<T>[]`,
    // but the consumer's column config is always a frozen `as const` array.
    // Cast to satisfy the API; the array is not mutated by TanStack.
    columns: visibleColumns as unknown as import('@tanstack/react-table').ColumnDef<T>[],
    getCoreRowModel: getCoreRowModel(),
    getRowId: (row) => row.id,
  });

  // Loading shell — keep simple in the scaffold; Story 2.7 introduces the
  // full empty-state tree (no-rows-match / no-rows-exist / stale-cursor).
  if (isLoading) {
    return (
      <div
        data-testid={`${tableTestId}-loading`}
        className="py-12 text-center text-sm text-muted-foreground"
      >
        Loading…
      </div>
    );
  }
  if (isError) {
    return (
      <DataTableEmpty
        kind="no-rows-match"
        title="Failed to load"
        message="Try again or check the backend."
      />
    );
  }

  // Story 2.4 — search input slot for the toolbar (left of filters).
  const searchSlot =
    searchable && onQChange ? (
      <DataTableSearch value={q} onQChange={onQChange} totalCount={totalCount} />
    ) : null;

  const leftSlot =
    searchSlot || filterSlot.length > 0 ? (
      <>
        {searchSlot}
        {filterSlot}
      </>
    ) : null;

  // Story 2.5 — total-count display in the right slot.
  // Story 2.10/2.11 — density toggle + column-visibility menu also in right slot.
  const columnVisibilityItems = columns
    .filter((c) => c.hideable !== false)
    .map((c) => ({
      id: c.id,
      label: typeof c.header === 'string' ? c.header : c.id,
      hidden: hiddenColumns.has(c.id),
      sticky: c.sticky,
    }));
  const rightSlot = (
    <>
      {totalCount !== undefined && (
        <DataTableTotalCount
          totalCount={totalCount}
          rowsRendered={data.length}
          cursorStackLength={cursorStackLength}
        />
      )}
      <DataTableDensityToggle density={density} onChange={setDensity} />
      <DataTableColumnVisibility
        items={columnVisibilityItems}
        onToggle={(id) => hiddenColumns.toggle(id)}
      />
    </>
  );

  // Story 2.7 — three empty-state shapes per FR-9.
  // Branch logic:
  //   - data empty + totalCount > 0 + cursor active → stale-cursor
  //   - data empty + (any filter | q) active        → no-rows-match
  //   - data empty otherwise                        → no-rows-exist (consumer copy)
  let emptyBranch: 'stale-cursor' | 'no-rows-match' | 'no-rows-exist' | null = null;
  if (data.length === 0) {
    if (totalCount !== undefined && totalCount > 0 && cursor) {
      emptyBranch = 'stale-cursor';
    } else if (anyMatcherActive) {
      emptyBranch = 'no-rows-match';
    } else {
      emptyBranch = 'no-rows-exist';
    }
  }

  return (
    <div className="space-y-3">
      <DataTableToolbar tableId={props.tableId} leftSlot={leftSlot} rightSlot={rightSlot} />
      {emptyBranch === 'no-rows-exist' ? (
        <DataTableEmpty
          kind="no-rows-exist"
          title={emptyStateNoRows.title}
          message={emptyStateNoRows.message}
          primaryCta={emptyStateNoRows.primaryCta}
        />
      ) : emptyBranch === 'no-rows-match' ? (
        <DataTableEmpty
          kind="no-rows-match"
          title={props.emptyStateNoMatch?.title}
          message={props.emptyStateNoMatch?.message}
          onClearFilters={onClearMatchers}
        />
      ) : emptyBranch === 'stale-cursor' ? (
        <DataTableEmpty
          kind="stale-cursor"
          onReturnToFirstPage={onCursorChange ? () => onCursorChange(null) : undefined}
        />
      ) : (
        <>
          {/* Story 2.9 — bulk-action toolbar above the table when selectable + actions supplied. */}
          {selectable && bulkActions && bulkActions.length > 0 && (
            <DataTableBulkActions
              selectedIds={Array.from(selectedIds)}
              actions={bulkActions}
              onClear={clearSelection}
            />
          )}
          <Table data-testid={tableTestId}>
            {/* Story 2.8 — sticky header (FR-11). Tailwind `position: sticky` +
                `top: 0` + `bg-background` so rows don't bleed through on scroll
                inside a constrained parent (consumer wraps in a max-h Card). */}
            <TableHeader className="sticky top-0 bg-background z-10">
              {table.getHeaderGroups().map((headerGroup) => (
                <TableRow key={headerGroup.id}>
                  {selectable && (
                    <TableHead className="w-10">
                      <input
                        type="checkbox"
                        aria-label="Select all rows on this page"
                        data-testid="data-table-select-all"
                        className="h-4 w-4 rounded border-border accent-primary"
                        checked={allOnPageSelected}
                        ref={(el) => {
                          if (el) el.indeterminate = someOnPageSelected;
                        }}
                        onChange={toggleAllOnPage}
                      />
                    </TableHead>
                  )}
                  {headerGroup.headers.map((header) => {
                    const colDef = header.column.columnDef as DataTableColumnDef<T>;
                    const rawHeader = header.isPlaceholder
                      ? null
                      : flexRender(colDef.header, header.getContext());
                    // Story 2.8 — tooltip-enabled column headers (FR-12).
                    // For sortable columns, pass the tooltip via the
                    // `trailing` slot on `DataTableSortHeader` so it renders
                    // outside the sort `<button>` — avoids invalid
                    // button-in-button nesting and accidental sort on
                    // tooltip interaction.
                    const tooltipNode = colDef.tooltipKey ? (
                      <InfoTooltip glossaryKey={colDef.tooltipKey} />
                    ) : null;
                    if (colDef.sortable && onSortChange) {
                      return (
                        <TableHead key={header.id} className={cellPaddingClass}>
                          <DataTableSortHeader
                            label={rawHeader}
                            sortKey={colDef.sortKey ?? colDef.id}
                            activeSort={sort}
                            onSortChange={onSortChange}
                            firstClickDirection={colDef.firstClickDirection}
                            sortDirections={colDef.sortDirections}
                            trailing={tooltipNode}
                          />
                        </TableHead>
                      );
                    }
                    return (
                      <TableHead key={header.id} className={cellPaddingClass}>
                        {tooltipNode ? (
                          <span className="inline-flex items-center gap-1">
                            {rawHeader}
                            {tooltipNode}
                          </span>
                        ) : (
                          rawHeader
                        )}
                      </TableHead>
                    );
                  })}
                </TableRow>
              ))}
            </TableHeader>
            <TableBody>
              {table.getRowModel().rows.map((row, idx) => (
                <TableRow
                  key={row.id}
                  data-testid={rowTestId(row.original)}
                  ref={(el) => {
                    rowRefs.current[idx] = el;
                  }}
                  tabIndex={keyboardNav ? (focusedRowIndex === idx ? 0 : -1) : undefined}
                  onKeyDown={keyboardNav ? (e) => handleRowKeyDown(e, idx) : undefined}
                  onFocus={keyboardNav ? () => setFocusedRowIndex(idx) : undefined}
                >
                  {selectable && (
                    <TableCell className="w-10">
                      <input
                        type="checkbox"
                        aria-label="Select row"
                        data-testid={`data-table-select-row-${row.original.id}`}
                        className="h-4 w-4 rounded border-border accent-primary"
                        checked={selectedIds.has(row.original.id)}
                        onChange={() => toggleRow(row.original.id)}
                      />
                    </TableCell>
                  )}
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id} className={cellPaddingClass}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </>
      )}
      {/* Story 2.7 — wrap CursorPaginator so consumers stop importing it directly. */}
      {data.length > 0 && onCursorChange && onPageSizeChange && (
        <CursorPaginator
          hasMore={has_more}
          onNext={has_more && next_cursor ? goNext : undefined}
          onPrev={cursorStack.length > 1 ? goPrev : undefined}
          pageSize={pageSize}
          onPageSizeChange={onPageSizeChange}
          totalCount={totalCount}
          pageSizeOptions={pageSizeOptions}
        />
      )}
    </div>
  );
}
