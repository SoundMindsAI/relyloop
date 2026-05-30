// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Column configuration + sort codec for `<TrialsTable>`
 * (feat_data_table_primitive Story 3.7).
 *
 * Trials' backend `?sort=` Literal predates the generic `<col>:<dir>` shape
 * Story 1.3 introduced for other resources — it carries the fused tokens
 * `primary_metric_desc`, `primary_metric_asc`, `ended_at_desc`,
 * `ended_at_asc`, `optuna_trial_number_asc`. The `trialsSortCodec`
 * translates between the DataTable internal `(col, dir)` form and that
 * wire format. Note that `optuna_trial_number_desc` does NOT exist in
 * `TrialSortKey`; the trial-number column is therefore configured with
 * `sortDirections: ['asc']` so the cycle skips desc.
 *
 * 5 columns: trial number (asc-only sortable), Status (not sortable, no
 * filter — `/api/v1/studies/{id}/trials` has no ?status= param), Primary
 * metric (sortable desc-first), Ended at (sortable desc-first), Duration
 * (not sortable — duration is not a TrialSortKey), Params (not sortable).
 */
import type { SortCodec } from '@/components/common/data-table-sort-header';
import type { DataTableColumnDef } from '@/components/common/types';
import { StatusBadge } from '@/components/common/status-badge';
import type { TrialDetail } from '@/lib/api/studies';

const TRIAL_WIRE_TO_INTERNAL: Record<string, { col: string; dir: 'asc' | 'desc' }> = {
  primary_metric_desc: { col: 'primary_metric', dir: 'desc' },
  primary_metric_asc: { col: 'primary_metric', dir: 'asc' },
  ended_at_desc: { col: 'ended_at', dir: 'desc' },
  ended_at_asc: { col: 'ended_at', dir: 'asc' },
  optuna_trial_number_asc: { col: 'optuna_trial_number', dir: 'asc' },
};

export const trialsSortCodec: SortCodec = {
  encode: (col, dir) => `${col}_${dir}`,
  decode: (wire) => TRIAL_WIRE_TO_INTERNAL[wire] ?? null,
};

export const trialsColumns: DataTableColumnDef<TrialDetail>[] = [
  {
    id: 'optuna_trial_number',
    header: '#',
    accessorKey: 'optuna_trial_number',
    sortable: true,
    firstClickDirection: 'asc',
    // Surface the "what is a trial" explainer on the column that shows the
    // Optuna trial number — the bare "#" header otherwise reads as "row
    // index" to a first-time operator.
    tooltipKey: 'trial',
    // optuna_trial_number_desc does not exist in the TrialSortKey Literal;
    // constrain the cycle so the second click clears to unsorted instead
    // of trying to advance to an unsupported direction.
    sortDirections: ['asc'],
  },
  {
    id: 'status',
    header: 'Status',
    accessorKey: 'status',
    tooltipKey: 'trial.status',
    cell: ({ row }) => <StatusBadge kind="trial" value={row.original.status} />,
  },
  {
    id: 'primary_metric',
    header: 'Primary metric',
    accessorKey: 'primary_metric',
    sortable: true,
    firstClickDirection: 'desc',
    tooltipKey: 'trial.primary_metric',
    cell: ({ row }) =>
      row.original.primary_metric != null ? row.original.primary_metric.toFixed(4) : '—',
  },
  {
    id: 'ended_at',
    header: 'Ended at',
    accessorKey: 'ended_at',
    sortable: true,
    firstClickDirection: 'desc',
    cell: ({ row }) =>
      row.original.ended_at ? (
        <span className="whitespace-nowrap">
          {new Date(row.original.ended_at).toLocaleString()}
        </span>
      ) : (
        <span className="text-muted-foreground">—</span>
      ),
  },
  {
    id: 'duration_ms',
    header: 'Duration (ms)',
    accessorKey: 'duration_ms',
    tooltipKey: 'trial.duration_ms',
    cell: ({ row }) => row.original.duration_ms ?? <span className="text-muted-foreground">—</span>,
  },
  {
    id: 'params',
    header: 'Params',
    tooltipKey: 'trial.params',
    hideable: false,
    cell: ({ row }) => (
      <span className="font-mono text-xs">{JSON.stringify(row.original.params)}</span>
    ),
  },
];
