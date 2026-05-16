/**
 * Shared types for the `<DataTable>` primitive (feat_data_table_primitive Epic 2).
 *
 * The primitive is presentation-only — the consumer's TanStack Query hook owns
 * server state, and the consumer's `useDataTableUrlState` hook owns URL state.
 * DataTable receives them as props (controlled component pattern per spec FR-8).
 *
 * Story 2.1 ships ONLY the scaffold types — sortable headers, filters, search,
 * selection, column visibility, density, and keyboard nav land in subsequent
 * Epic 2 stories. The interfaces below are forward-compatible: every Story
 * 2.2–2.13 feature has its prop shape declared here, and the primitive shell
 * progressively wires them in.
 */

import type { ColumnDef as TanstackColumnDef } from '@tanstack/react-table';

import type { GlossaryKey } from '@/lib/glossary';

// ---------------------------------------------------------------------------
// Filter kinds (Story 2.3 — wired in `<DataTableFilterChips>` / `<DataTableFkSelect>`)
// ---------------------------------------------------------------------------

export interface DataTableEnumFilter {
  kind: 'enum';
  /** The exact wire values the backend accepts. Imported as-const from `@/lib/enums`. */
  wireValues: readonly string[];
  /**
   * Backend allowlist citation, e.g. "backend/app/api/v1/schemas.py StudyStatusWire".
   * Asserted by the Story 2.13 column-config-discipline test.
   */
  sourceOfTruth: string;
  /** Optional user-facing label override; defaults to the wire value verbatim. */
  label?: (value: string) => string;
}

export interface DataTableFkSelectFilter<T = unknown> {
  kind: 'fk-select';
  /**
   * Hook the primitive calls to load the options. Pattern matches the existing
   * `cluster-filter-select.tsx` precedent — page sizes are conservatively capped
   * at 200 per the precedent's comment.
   */
  useOptions: () => { data: { id: string; label: string }[]; isLoading: boolean };
  /** Backend FK column citation, e.g. "DB FK on proposals.template_id". */
  sourceOfTruth: string;
  placeholder: string;
  /** Reserved for future per-row data shape; not used in the scaffold. */
  _phantom?: T;
}

export type DataTableFilter = DataTableEnumFilter | DataTableFkSelectFilter;

// ---------------------------------------------------------------------------
// Column definition — intersection with TanStack's ColumnDef union
// (interface-extends-Omit erases narrowing; intersection preserves it).
// ---------------------------------------------------------------------------

/**
 * Column definition consumed by `<DataTable>`. Built on TanStack Table's
 * `ColumnDef` with RelyLoop-specific extras: sortable cycle, sortKey wire form,
 * `firstClickDirection`, `sortDirections` (constrains the cycle for backends
 * that only accept a subset, e.g. trials' `optuna_trial_number_asc`-only),
 * enum/fk-select filters, tooltip key, hideability, sticky.
 */
export type DataTableColumnDef<T extends { id: string }, TValue = unknown> = TanstackColumnDef<
  T,
  TValue
> & {
  /** Required: a stable string id used for `?sort=`, `?<col>=`, and the col-vis menu. */
  id: string;
  sortable?: boolean;
  /**
   * The wire-form column name used in `?sort=<sortKey>:<dir>`. Defaults to
   * `id` when omitted (typical case — column id matches wire name).
   */
  sortKey?: string;
  /** First-click direction (default `'asc'`). Set `'desc'` on metric-shaped columns. */
  firstClickDirection?: 'asc' | 'desc';
  /**
   * Constrain the sort cycle. Default `['asc', 'desc']` (full three-state cycle).
   * Set to `['asc']` or `['desc']` for columns where the backend Literal only
   * accepts one direction (e.g. trials' `optuna_trial_number_asc`). The cycle
   * skips directions not in this list.
   */
  sortDirections?: readonly ('asc' | 'desc')[];
  filter?: DataTableFilter;
  tooltipKey?: GlossaryKey;
  /** Default `true` — column appears in the visibility menu. */
  hideable?: boolean;
  /** Default `false` — sticky columns aren't hideable (e.g. selection checkbox). */
  sticky?: boolean;
};

// ---------------------------------------------------------------------------
// Bulk actions (Story 2.9 — wired in `<DataTableBulkActions>`)
// ---------------------------------------------------------------------------

export interface BulkAction {
  label: string;
  onClick: (selectedIds: string[], clearSelection: () => void) => void;
  variant?: 'default' | 'destructive';
  testid?: string;
}

// ---------------------------------------------------------------------------
// Primitive props
// ---------------------------------------------------------------------------

/**
 * Props accepted by `<DataTable>`. Generic `T` is constrained to `{ id: string }`
 * so every consumer's summary row carries a stable id field — TanStack Table's
 * `getRowId: (row) => row.id` keys row selection, keyboard activation, and the
 * `<TableRow data-testid>` shape on backend UUIDs rather than array indices.
 *
 * Controlled props (`urlState`, setters, page size, etc.) land in Story 2.6's
 * URL-state refactor. The scaffold uses optional props so 2.2–2.5 stories can
 * iterate without breaking the type-check until 2.6 lifts the state.
 */
export interface DataTableProps<T extends { id: string }> {
  /** Stable id for localStorage keys (col-vis, density) and testids. */
  tableId: string;

  columns: readonly DataTableColumnDef<T>[];
  data: readonly T[];
  isLoading: boolean;
  isError: boolean;

  /** `X-Total-Count` header value (consumer parses + passes through). */
  totalCount?: number;
  has_more: boolean;
  next_cursor: string | null;

  /** Whether to render the toolbar's search input (Story 2.4). */
  searchable?: boolean;

  /** Whether to render the selection checkbox column (Story 2.9). */
  selectable?: boolean;

  /** Default `true` — Arrow/Enter/Space row interaction (Story 2.12). */
  keyboardNav?: boolean;

  defaultPageSize?: number;

  /** Called on Enter or row click; typically navigates to detail. */
  onRowActivate?: (rowId: string) => void;

  /** Called on every selection change; bulk-action wiring (Story 2.9). */
  onSelectionChange?: (selectedIds: string[]) => void;

  /** Consumer-supplied bulk actions; toolbar lights up when ≥1 row selected. */
  bulkActions?: readonly BulkAction[];

  /** Empty-state copy when `totalCount === 0` AND no filters/q are active. */
  emptyStateNoRows: { title: string; message: string; primaryCta?: React.ReactNode };

  /** Empty-state copy when filters or q are active but matched zero rows. */
  emptyStateNoMatch?: { title?: string; message?: string };

  /**
   * Required for E2E spec compatibility — preserves the existing
   * `data-testid="<resource>-table"` shape on migrated tables.
   */
  tableTestId: string;

  /**
   * Required — derives the per-row `data-testid` from the row id. Existing
   * resources use distinct prefixes (`study-row-<id>`, `proposal-row-<id>`,
   * `row-<id>` for queries-table), so the consumer supplies the mapper.
   */
  rowTestId: (row: T) => string;

  /**
   * Story 2.2 — sort URL state (transient prop until Story 2.6 lifts URL
   * ownership to a `useDataTableUrlState` hook at the consumer). Optional
   * during the 2.2-2.5 build-out; becomes required when 2.6 lands.
   *
   * Wire shape: ``<col>:<asc|desc>`` for the default column-name encoder,
   * or the resource's combined-wire form for trials (the consumer-supplied
   * encoder maps `(col, dir)` to/from the wire value at column-config level).
   */
  sort?: string | null;
  onSortChange?: (next: string | null) => void;

  /**
   * Story 2.3 — filter URL state (transient until Story 2.6). Map of column
   * id → active wire value (`null` or absent = "all" / no filter). The
   * primitive renders chip rows / FK selects in the toolbar for every column
   * with `column.filter` set.
   */
  filters?: Record<string, string | null | undefined>;
  onFilterChange?: (columnId: string, next: string | null) => void;

  /**
   * Story 2.4 — debounced text search URL state. Transient until Story 2.6.
   * Only rendered when `searchable === true`.
   */
  q?: string | null;
  onQChange?: (next: string | null) => void;

  /**
   * Story 2.5 — total-count display state. `cursorStackLength` is the
   * count of cursor pushes the user has made via in-app Next clicks
   * (1 = first page; 2 = page 2; etc.). When the user reloads or shares
   * a URL with `?cursor=`, the consumer cannot reconstruct this number
   * — leave at 1 and the toolbar renders the cursor-paginator-honest
   * "Showing N rows (of M matching)" wording per FR-7.
   */
  cursorStackLength?: number;
}
