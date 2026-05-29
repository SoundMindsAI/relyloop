/**
 * Column configuration for `<StudiesTable>` (feat_data_table_primitive Story 3.1).
 *
 * Six columns mirroring the legacy studies-table.tsx layout, lifted into a
 * declarative TanStack ColumnDef array consumed by the shared `<DataTable>`
 * primitive. The `status` filter is the planned migration target of the
 * deleted `<StudyStatusFilterChips>` — wire values are sourced from
 * `STUDY_STATUS_VALUES` in `@/lib/enums` (which itself carries the canonical
 * `// Values must match backend/app/api/v1/schemas.py StudyStatusWire`
 * source-of-truth comment per the Story 2.13 lint guard).
 */
import Link from 'next/link';

import { InfoTooltip } from '@/components/common/info-tooltip';
import { StatusBadge } from '@/components/common/status-badge';
import { Badge } from '@/components/ui/badge';
import type { DataTableColumnDef } from '@/components/common/types';
import type { StudySummary } from '@/lib/api/studies';
import { STUDY_STATUS_VALUES } from '@/lib/enums';

/**
 * Threshold heuristic for the "ceiling" badge — when `best_metric` is at or
 * very close to the metric's upper bound, the score is almost always pinned
 * by judgment-density rather than earned by the optimizer. The detail page's
 * Confidence panel gives the deeper signal (per-query outcomes, runner-up
 * gap, CI band); this badge is the at-a-glance cue on the list view.
 */
const METRIC_CEILING_THRESHOLD = 0.99;

export const studiesColumns: DataTableColumnDef<StudySummary>[] = [
  {
    id: 'name',
    header: 'Name',
    accessorKey: 'name',
    sortable: true,
    cell: ({ row }) => (
      <Link
        href={`/studies/${row.original.id}`}
        className="text-blue-600 underline-offset-4 hover:underline"
      >
        {row.original.name}
      </Link>
    ),
  },
  {
    id: 'cluster_id',
    header: 'Cluster',
    accessorKey: 'cluster_id',
    sticky: true,
    // Plan Story 3.1: cluster_id is not hideable. sticky force-shows in
    // render; hideable: false also hides it from the col-vis menu.
    hideable: false,
    cell: ({ row }) => <span className="font-mono text-xs">{row.original.cluster_id}</span>,
  },
  {
    id: 'status',
    header: 'Status',
    accessorKey: 'status',
    sortable: true,
    filter: {
      kind: 'enum',
      wireValues: STUDY_STATUS_VALUES,
      sourceOfTruth: 'backend/app/api/v1/schemas.py StudyStatusWire',
    },
    cell: ({ row }) => <StatusBadge kind="study" value={row.original.status} />,
  },
  {
    id: 'best_metric',
    header: 'Best metric',
    accessorKey: 'best_metric',
    sortable: true,
    firstClickDirection: 'desc',
    cell: ({ row }) => {
      const m = row.original.best_metric;
      if (m == null) return <span className="text-muted-foreground">—</span>;
      // The CEILING badge (best_metric >= 0.99) only makes sense for
      // maximize objectives, where ≥0.99 means the metric is pinned at its
      // upper bound. For a minimize objective a 0.99 is a *bad* score, not
      // a ceiling — labeling it "pinned at ceiling" would be the exact
      // opposite of the truth. Gate on direction so a minimize study shows
      // no false badge. Per bug_ceiling_badge_assumes_maximize_direction.
      //
      // Use `!== 'minimize'` (not `=== 'maximize'`) so an absent/undefined
      // direction defaults to maximize — matching the backend's own
      // `objective.get("direction", "maximize")` default and staying
      // backward-compatible during a rolling deploy where the frontend
      // ships ahead of the backend (old API responses lack the field).
      // Per Gemini PR #305 review.
      const saturated = row.original.direction !== 'minimize' && m >= METRIC_CEILING_THRESHOLD;
      return (
        <span className="inline-flex items-center gap-1.5">
          <span>{m.toFixed(3)}</span>
          {saturated && (
            <span
              className="inline-flex items-center gap-0.5"
              data-testid={`best-metric-ceiling-${row.original.id}`}
            >
              <Badge variant="warning" className="text-[10px] uppercase tracking-wide">
                Ceiling
              </Badge>
              <InfoTooltip glossaryKey="study.best_metric.saturated" />
            </span>
          )}
        </span>
      );
    },
  },
  {
    id: 'created_at',
    header: 'Created',
    accessorKey: 'created_at',
    sortable: true,
    firstClickDirection: 'desc',
    cell: ({ row }) => (
      <span className="whitespace-nowrap">
        {new Date(row.original.created_at).toLocaleString()}
      </span>
    ),
  },
  {
    id: 'completed_at',
    header: 'Completed',
    accessorKey: 'completed_at',
    sortable: true,
    hideable: true,
    cell: ({ row }) =>
      row.original.completed_at ? (
        <span className="whitespace-nowrap">
          {new Date(row.original.completed_at).toLocaleString()}
        </span>
      ) : (
        <span className="text-muted-foreground">—</span>
      ),
  },
];
