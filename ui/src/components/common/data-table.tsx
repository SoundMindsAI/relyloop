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

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

import { DataTableEmpty } from './data-table-empty';
import { DataTableFilterChips } from './data-table-filter-chips';
import { DataTableFkSelect } from './data-table-fk-select';
import { DataTableSearch } from './data-table-search';
import { DataTableSortHeader } from './data-table-sort-header';
import { DataTableToolbar } from './data-table-toolbar';
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
  } = props;

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

  return (
    <div className="space-y-3">
      <DataTableToolbar tableId={props.tableId} leftSlot={leftSlot} />
      {data.length === 0 ? (
        <DataTableEmpty
          kind="no-rows-exist"
          title={emptyStateNoRows.title}
          message={emptyStateNoRows.message}
          primaryCta={emptyStateNoRows.primaryCta}
        />
      ) : (
        <Table data-testid={tableTestId}>
          <TableHeader>
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map((header) => {
                  const colDef = header.column.columnDef as DataTableColumnDef<T>;
                  const rawHeader = header.isPlaceholder
                    ? null
                    : flexRender(colDef.header, header.getContext());
                  // Wrap with the sort header when the column declares `sortable`.
                  // Falls back to the raw rendered header for non-sortable columns.
                  if (colDef.sortable && onSortChange) {
                    return (
                      <TableHead key={header.id}>
                        <DataTableSortHeader
                          label={rawHeader}
                          sortKey={colDef.sortKey ?? colDef.id}
                          activeSort={sort}
                          onSortChange={onSortChange}
                          firstClickDirection={colDef.firstClickDirection}
                          sortDirections={colDef.sortDirections}
                        />
                      </TableHead>
                    );
                  }
                  return <TableHead key={header.id}>{rawHeader}</TableHead>;
                })}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {table.getRowModel().rows.map((row) => (
              <TableRow key={row.id} data-testid={rowTestId(row.original)}>
                {row.getVisibleCells().map((cell) => (
                  <TableCell key={cell.id}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
