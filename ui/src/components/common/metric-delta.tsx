// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { cn } from '@/lib/utils';

export interface MetricDeltaProps {
  baseline: number | null | undefined;
  achieved: number | null | undefined;
  /** Number of decimal places shown for baseline/achieved. Default 3. */
  precision?: number;
  className?: string;
}

/**
 * Renders "baseline → achieved (±delta_pct%)" with green/red coloring.
 * - baseline missing / null → "(new)" instead of an infinite-percent
 * - achieved missing → "—"
 * - baseline = 0 with non-zero achieved → "(new)" (avoid Infinity)
 */
export function MetricDelta({ baseline, achieved, precision = 3, className }: MetricDeltaProps) {
  if (achieved == null) {
    return <span className={cn('text-muted-foreground', className)}>—</span>;
  }
  if (baseline == null || baseline === 0) {
    return (
      <span className={cn('tabular-nums text-foreground', className)}>
        {achieved.toFixed(precision)} <span className="text-muted-foreground">(new)</span>
      </span>
    );
  }
  const deltaPct = ((achieved - baseline) / baseline) * 100;
  const sign = deltaPct >= 0 ? '+' : '';
  const colorClass =
    deltaPct > 0
      ? 'text-green-700 dark:text-green-400'
      : deltaPct < 0
        ? 'text-red-700 dark:text-red-400'
        : 'text-foreground';
  return (
    <span className={cn('inline-flex items-baseline gap-1 tabular-nums', className)}>
      <span className="text-foreground">
        {baseline.toFixed(precision)} → {achieved.toFixed(precision)}
      </span>
      <span className={cn('font-medium', colorClass)} data-testid="metric-delta-pct">
        ({sign}
        {deltaPct.toFixed(1)}%)
      </span>
    </span>
  );
}
