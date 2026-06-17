// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

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
import type { ConvergenceVerdict } from '@/lib/enums';

/**
 * Threshold heuristic for the "ceiling" badge — when `best_metric` is at or
 * very close to the metric's upper bound, the score is almost always pinned
 * by judgment-density rather than earned by the optimizer. The detail page's
 * Confidence panel gives the deeper signal (per-query outcomes, runner-up
 * gap, CI band); this badge is the at-a-glance cue on the list view.
 */
const METRIC_CEILING_THRESHOLD = 0.99;

/**
 * Percent lift of `best` over the `baseline` (starting) metric, formatted with
 * a leading sign. Mirrors the digest panel's `deltaPct`
 * (`ui/src/components/studies/digest-panel.tsx`) so the studies list and the
 * study-detail digest tell the same `start → best (delta)` story; keep the two
 * in sync. Returns an em-dash when either side is absent and `(new)` when the
 * baseline is exactly 0 (no meaningful percentage off a zero base).
 */
function deltaPct(baseline: number | null | undefined, best: number | null | undefined): string {
  if (baseline == null || best == null) return '—';
  if (baseline === 0) return '(new)';
  const pct = ((best - baseline) / Math.abs(baseline)) * 100;
  const sign = pct >= 0 ? '+' : '';
  return `${sign}${pct.toFixed(1)}%`;
}

/**
 * Compact convergence-verdict badge map for the studies-list column
 * (feat_studies_convergence_visibility Story 1.2 / FR-4). Typed
 * `satisfies Record<ConvergenceVerdict, ...>` so a verdict added to (or
 * removed from) the backend `ConvergenceVerdict` Literal — mirrored by
 * `CONVERGENCE_VERDICT_VALUES` in `@/lib/enums` — becomes a COMPILE error
 * here, not a silent missing badge. The detail page's `<ConvergencePanel>`
 * uses the fuller labels ("Still improving when it stopped", "Too few
 * trials to tell"); the dense list uses these compact forms.
 *
 * Wire values must match backend/app/domain/study/convergence.py
 * ConvergenceVerdict (via CONVERGENCE_VERDICT_VALUES in @/lib/enums).
 */
const VERDICT_BADGE = {
  converged: { label: 'Converged', variant: 'success' as const },
  still_improving: { label: 'Improving', variant: 'warning' as const },
  too_few_trials: { label: 'Too few trials', variant: 'warning' as const },
} satisfies Record<ConvergenceVerdict, { label: string; variant: 'success' | 'warning' }>;

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
    // Sorts on `best_metric` (the winner) but renders the full
    // `starting → best (lift)` story so a best score is read against the
    // baseline it improved on — the same framing the study-detail digest
    // panel uses. The `accessorKey`/`id` stay `best_metric` so the existing
    // `best_metric:asc|desc` sort wiring is unchanged.
    id: 'best_metric',
    header: 'Starting → best',
    accessorKey: 'best_metric',
    sortable: true,
    firstClickDirection: 'desc',
    cell: ({ row }) => {
      const baseline = row.original.baseline_metric;
      const best = row.original.best_metric;
      // No winner yet (queued/running, or a study that never completed) → a
      // single em-dash, matching the prior best-metric-only behavior. The
      // baseline alone isn't worth a row when there's no "best" to compare it
      // against.
      if (best == null) return <span className="text-muted-foreground">—</span>;
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
      const saturated = row.original.direction !== 'minimize' && best >= METRIC_CEILING_THRESHOLD;
      return (
        <span
          className="inline-flex items-center gap-1.5"
          data-testid={`metric-delta-${row.original.id}`}
        >
          <span className="tabular-nums text-muted-foreground">
            {baseline != null ? baseline.toFixed(3) : '—'}
          </span>
          <span className="text-muted-foreground">→</span>
          <span className="tabular-nums">{best.toFixed(3)}</span>
          <span className="text-xs text-muted-foreground" data-testid={`metric-lift-${row.original.id}`}>
            ({deltaPct(baseline, best)})
          </span>
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
    id: 'trial_count',
    header: 'Trials',
    // tooltipKey renders an <InfoTooltip> in the header (data-table.tsx:435)
    // while keeping `header` a string so the column-visibility menu shows
    // "Trials" (not the column id) — see data-table.tsx:316.
    tooltipKey: 'study.trial_count',
    accessorKey: 'trial_count',
    sortable: false,
    hideable: true,
    cell: ({ row }) => <span className="tabular-nums">{row.original.trial_count}</span>,
  },
  {
    id: 'convergence_verdict',
    header: 'Convergence',
    tooltipKey: 'convergence_verdict',
    accessorKey: 'convergence_verdict',
    sortable: false,
    hideable: true,
    cell: ({ row }) => {
      const verdict = row.original.convergence_verdict;
      // null verdict (in-flight, invalid-direction, or < 5 complete trials)
      // renders an em-dash, never a badge — matches the detail panel's
      // null-state behavior.
      if (verdict == null) return <span className="text-muted-foreground">—</span>;
      // `verdict` is narrowed to the ConvergenceVerdict union and VERDICT_BADGE
      // is `satisfies Record<ConvergenceVerdict, ...>`, so this lookup is
      // provably total + safe at compile time — not user-controlled object
      // injection.
      // eslint-disable-next-line security/detect-object-injection
      const badge = VERDICT_BADGE[verdict];
      // Forward-compat guard (Gemini PR #438 review, accepted): convergence_verdict
      // is a backend-COMPUTED classification (backend/app/domain/study/convergence.py),
      // not a fixed DB-enum, so a newer backend could emit a verdict this snapshot
      // doesn't map during a rolling deploy. Without this, an unmapped value would
      // throw on `badge.variant` and crash the whole table render. Falls back to the
      // same em-dash as the null state. Matches the StatusBadge `?? 'secondary'`
      // pattern + the best_metric column's rolling-deploy backward-compat stance.
      if (!badge) return <span className="text-muted-foreground">—</span>;
      return (
        <span
          className="inline-flex items-center"
          data-testid={`convergence-verdict-${row.original.id}`}
          data-verdict={verdict}
        >
          <Badge variant={badge.variant} className="text-[10px] uppercase tracking-wide">
            {badge.label}
          </Badge>
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
