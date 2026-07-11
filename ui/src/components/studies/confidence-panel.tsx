// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

import { InfoTooltip } from '@/components/common/info-tooltip';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { formatMetricLabel } from '@/lib/labels';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type { components } from '@/lib/types';

type ConfidenceShape = components['schemas']['ConfidenceShape'];

export interface ConfidencePanelProps {
  confidence: ConfidenceShape | null | undefined;
}

// Values must match backend/app/domain/study/confidence.py RunnerUpClassification.
const RUNNER_UP_BADGE: Record<string, { label: string; variant: 'success' | 'warning' }> = {
  robust_plateau: { label: 'Robust plateau', variant: 'success' },
  sharp_peak: { label: 'Sharp peak', variant: 'warning' },
};

// Values must match backend/app/domain/study/confidence.py ConvergenceRegime.
const CONVERGENCE_BADGE: Record<string, { label: string; variant: 'success' | 'warning' }> = {
  early_held: { label: 'Early-and-held', variant: 'success' },
  late_rising: { label: 'Late-rising', variant: 'warning' },
  noisy: { label: 'Noisy', variant: 'warning' },
};

function formatComparison(comparison: string): string {
  // Values must match backend/app/domain/study/confidence.py ComparisonAgainst.
  // Phase 1 only emits `runner_up`; `baseline` reserved for Phase 2.
  return comparison === 'baseline' ? 'baseline' : 'runner-up';
}

export function ConfidencePanel({ confidence }: ConfidencePanelProps) {
  // FR-7 whole-object null path: render nothing — no empty shell. The page
  // visual rhythm (header → trials → digest) is preserved for old / still-
  // running studies.
  if (!confidence) return null;

  const { headline, ci_95, runner_up_gap, late_trial_stddev, convergence, per_query_outcomes } =
    confidence;
  const metricLabel = formatMetricLabel(headline.metric, headline.k);

  return (
    <Card data-testid="confidence-panel">
      <CardHeader>
        <CardTitle className="text-base">Confidence</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <p className="text-sm text-muted-foreground" data-testid="confidence-panel-explainer">
          Is this winner statistically reliable, or did the optimizer get lucky on one trial? The{' '}
          <strong>95% CI</strong> shows the headline metric's uncertainty range.{' '}
          <strong>Per-query outcomes</strong> tell you whether the lift is broad-based or driven by
          one query — the per-query tables below name the biggest winners and losers so you can spot
          patterns. <strong>Runner-up gap</strong>, <strong>late-trial 1σ</strong>, and{' '}
          <strong>convergence regime</strong> together indicate whether the optimizer settled on a
          robust plateau or a sharp peak. Hover any <em>(i)</em> icon for the full definition.
        </p>
        {/* Headline + CI band */}
        <section>
          <p className="flex items-center gap-1 text-xs uppercase text-muted-foreground">
            Headline metric
            <InfoTooltip glossaryKey="confidence.ci_95" />
          </p>
          <p className="mt-1 text-lg" data-testid="confidence-headline">
            <span className="font-semibold">{metricLabel}</span>
            {' = '}
            <span className="font-mono">{headline.value.toFixed(3)}</span>
            {ci_95 != null && (
              <span className="ml-2 text-sm text-muted-foreground" data-testid="confidence-ci">
                (95% CI {ci_95.low.toFixed(3)}–{ci_95.high.toFixed(3)}, N={headline.n_queries}{' '}
                queries)
              </span>
            )}
          </p>
        </section>

        {/* Per-query outcome chips + named regressors */}
        {per_query_outcomes != null && (
          <section data-testid="confidence-outcomes">
            <p className="flex items-center gap-1 text-xs uppercase text-muted-foreground">
              Per-query outcomes
              <InfoTooltip glossaryKey="confidence.per_query_outcomes" />
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
              <Badge variant="success" data-testid="outcome-improved">
                {per_query_outcomes.improved} Improved
              </Badge>
              <Badge variant="secondary" data-testid="outcome-unchanged">
                {per_query_outcomes.unchanged} Unchanged
              </Badge>
              <Badge variant="destructive" data-testid="outcome-regressed">
                {per_query_outcomes.regressed} Regressed
              </Badge>
              <span className="flex items-center gap-1 text-xs text-muted-foreground">
                vs {formatComparison(per_query_outcomes.comparison_against)}
                <InfoTooltip glossaryKey="confidence.comparison_against" />
              </span>
            </div>
            {per_query_outcomes.improved > 0 && per_query_outcomes.top_improvers.length > 0 && (
              <div className="mt-3" data-testid="confidence-improvers">
                <p className="mb-1 text-xs uppercase text-muted-foreground">
                  Queries that improved
                </p>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Query</TableHead>
                      <TableHead className="text-right">Winner</TableHead>
                      <TableHead className="text-right">
                        vs {formatComparison(per_query_outcomes.comparison_against)}
                      </TableHead>
                      <TableHead className="text-right">Δ</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {per_query_outcomes.top_improvers.map((row) => (
                      <TableRow key={row.query_id} data-testid={`improver-row-${row.query_id}`}>
                        <TableCell className="font-mono text-xs">{row.query_text}</TableCell>
                        <TableCell className="text-right font-mono">
                          {row.winner_score.toFixed(3)}
                        </TableCell>
                        <TableCell className="text-right font-mono">
                          {row.comparison_score.toFixed(3)}
                        </TableCell>
                        <TableCell className="text-right font-mono text-green-700">
                          +{row.delta.toFixed(3)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
            {per_query_outcomes.regressed > 0 && per_query_outcomes.top_regressors.length > 0 && (
              <div className="mt-3" data-testid="confidence-regressors">
                <p className="mb-1 text-xs uppercase text-muted-foreground">
                  Queries that regressed
                </p>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Query</TableHead>
                      <TableHead className="text-right">Winner</TableHead>
                      <TableHead className="text-right">
                        vs {formatComparison(per_query_outcomes.comparison_against)}
                      </TableHead>
                      <TableHead className="text-right">Δ</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {per_query_outcomes.top_regressors.map((row) => (
                      <TableRow key={row.query_id} data-testid={`regressor-row-${row.query_id}`}>
                        <TableCell className="font-mono text-xs">{row.query_text}</TableCell>
                        <TableCell className="text-right font-mono">
                          {row.winner_score.toFixed(3)}
                        </TableCell>
                        <TableCell className="text-right font-mono">
                          {row.comparison_score.toFixed(3)}
                        </TableCell>
                        <TableCell className="text-right font-mono text-red-700">
                          {row.delta.toFixed(3)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </section>
        )}

        {/* Secondary callouts row: runner-up gap, late-trial 1σ, convergence */}
        {(runner_up_gap != null || late_trial_stddev != null || convergence != null) && (
          <section className="grid gap-4 md:grid-cols-3" data-testid="confidence-callouts">
            {runner_up_gap != null && (
              <div data-testid="callout-runner-up-gap">
                <p className="flex items-center gap-1 text-xs uppercase text-muted-foreground">
                  Runner-up gap
                  <InfoTooltip glossaryKey="confidence.runner_up_gap" />
                </p>
                <div className="mt-1 flex items-center gap-2">
                  <span className="font-mono text-sm">{runner_up_gap.value.toFixed(3)}</span>
                  {/* Values must match backend/app/domain/study/confidence.py RunnerUpClassification. */}
                  <Badge
                    variant={RUNNER_UP_BADGE[runner_up_gap.classification]?.variant ?? 'warning'}
                  >
                    {RUNNER_UP_BADGE[runner_up_gap.classification]?.label ??
                      runner_up_gap.classification}
                  </Badge>
                </div>
              </div>
            )}
            {late_trial_stddev != null && (
              <div data-testid="callout-late-trial-stddev">
                <p className="flex items-center gap-1 text-xs uppercase text-muted-foreground">
                  Late-trial 1σ
                  <InfoTooltip glossaryKey="confidence.late_trial_stddev" />
                </p>
                <p className="mt-1 font-mono text-sm">{late_trial_stddev.value.toFixed(3)}</p>
              </div>
            )}
            {convergence != null && (
              <div data-testid="callout-convergence">
                <p className="flex items-center gap-1 text-xs uppercase text-muted-foreground">
                  Convergence
                  <InfoTooltip glossaryKey="confidence.convergence_regime" />
                </p>
                <div className="mt-1 flex items-center gap-2">
                  {/* Values must match backend/app/domain/study/confidence.py ConvergenceRegime. */}
                  <Badge variant={CONVERGENCE_BADGE[convergence.regime]?.variant ?? 'warning'}>
                    {CONVERGENCE_BADGE[convergence.regime]?.label ?? convergence.regime}
                  </Badge>
                  <span className="text-xs text-muted-foreground">
                    best at trial {convergence.best_at_trial} of {convergence.total_trials}
                  </span>
                </div>
              </div>
            )}
          </section>
        )}
      </CardContent>
    </Card>
  );
}
