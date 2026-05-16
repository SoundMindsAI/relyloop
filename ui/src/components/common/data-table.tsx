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
import { useEffect, useState } from 'react';

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

import { DataTableBulkActions } from './data-table-bulk-actions';
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
    cursorStackLength = 1,
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
  } = props;

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
          />,
        ];
      })
    : [];

  // TanStack Table model. `getRowId: (row) => row.id` keys row identity on the
  // backend UUID rather than the row index — required for stable selection,
  // keyboard activation, and per-row testids when rows shift across pages.
  const table = useReactTable<T>({
    data: data as T[],
    // TanStack Table's `columns` prop is typed as a mutable `ColumnDef<T>[]`,
    // but the consumer's column config is always a frozen `as const` array.
    // Cast to satisfy the API; the array is not mutated by TanStack.
    columns: columns as unknown as import('@tanstack/react-table').ColumnDef<T>[],
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
  const rightSlot =
    totalCount !== undefined ? (
      <DataTableTotalCount
        totalCount={totalCount}
        rowsRendered={data.length}
        cursorStackLength={cursorStackLength}
      />
    ) : null;

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
                    const tooltipNode = colDef.tooltipKey ? (
                      <InfoTooltip glossaryKey={colDef.tooltipKey} />
                    ) : null;
                    const labelWithTooltip = tooltipNode ? (
                      <span className="inline-flex items-center gap-1">
                        {rawHeader}
                        {tooltipNode}
                      </span>
                    ) : (
                      rawHeader
                    );
                    // Wrap with the sort header when the column declares `sortable`.
                    // Falls back to the raw rendered header for non-sortable columns.
                    if (colDef.sortable && onSortChange) {
                      return (
                        <TableHead key={header.id}>
                          <DataTableSortHeader
                            label={labelWithTooltip}
                            sortKey={colDef.sortKey ?? colDef.id}
                            activeSort={sort}
                            onSortChange={onSortChange}
                            firstClickDirection={colDef.firstClickDirection}
                            sortDirections={colDef.sortDirections}
                          />
                        </TableHead>
                      );
                    }
                    return <TableHead key={header.id}>{labelWithTooltip}</TableHead>;
                  })}
                </TableRow>
              ))}
            </TableHeader>
            <TableBody>
              {table.getRowModel().rows.map((row) => (
                <TableRow key={row.id} data-testid={rowTestId(row.original)}>
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
                    <TableCell key={cell.id}>
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
          onNext={has_more && next_cursor ? () => onCursorChange(next_cursor) : undefined}
          onPrev={cursor ? () => onCursorChange(null) : undefined}
          pageSize={pageSize}
          onPageSizeChange={onPageSizeChange}
          totalCount={totalCount}
          pageSizeOptions={pageSizeOptions}
        />
      )}
    </div>
  );
}
