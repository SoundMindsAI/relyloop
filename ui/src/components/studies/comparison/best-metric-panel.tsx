// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

export interface BestMetricPanelProps {
  llmMetric: number | null;
  ubiMetric: number | null;
  /** Objective direction; defaults to "maximize" upstream. */
  direction: 'maximize' | 'minimize';
  /** Label from `confidence.headline.metric`; neutral fallback otherwise. */
  metricLabel: string;
  /** True when the pairing carries an OBJECTIVE_MISMATCH warning. */
  objectiveMismatch?: boolean;
}

function fmt(v: number | null): string {
  return v == null ? '—' : v.toFixed(3);
}

/**
 * Best-metric scalar comparison (FR-6). Delta is always `ubi - llm` (NOT URL
 * order); "better/worse" respects `direction`. Delta suppressed when either
 * metric is null.
 */
export function BestMetricPanel({
  llmMetric,
  ubiMetric,
  direction,
  metricLabel,
  objectiveMismatch = false,
}: BestMetricPanelProps) {
  const haveBoth = llmMetric != null && ubiMetric != null;
  const delta = haveBoth ? (ubiMetric as number) - (llmMetric as number) : null;
  // "better" = the UBI study improved on the objective relative to LLM.
  const ubiBetter = delta == null ? null : direction === 'minimize' ? delta < 0 : delta > 0;

  return (
    <Card data-testid="compare-best-metric-panel">
      <CardHeader>
        <CardTitle className="text-base">Best {metricLabel}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <div className="grid grid-cols-2 gap-4 text-center">
          <div>
            <p className="text-xs uppercase text-muted-foreground">LLM</p>
            <p className="text-lg" data-testid="compare-best-metric-llm">
              {fmt(llmMetric)}
            </p>
          </div>
          <div>
            <p className="text-xs uppercase text-muted-foreground">UBI</p>
            <p className="text-lg" data-testid="compare-best-metric-ubi">
              {fmt(ubiMetric)}
            </p>
          </div>
        </div>
        {delta != null && (
          <p className="text-center text-sm" data-testid="compare-best-metric-delta">
            <span className={ubiBetter ? 'text-emerald-600' : 'text-destructive'}>
              {delta >= 0 ? '+' : ''}
              {delta.toFixed(3)}
            </span>{' '}
            <span className="text-muted-foreground">
              ({ubiBetter ? 'UBI better' : 'UBI worse'}, {direction})
            </span>
          </p>
        )}
        {objectiveMismatch && (
          <p
            className="text-center text-xs text-amber-700 dark:text-amber-400"
            data-testid="compare-best-metric-objective-caption"
          >
            metrics differ — delta is not directly comparable
          </p>
        )}
      </CardContent>
    </Card>
  );
}
