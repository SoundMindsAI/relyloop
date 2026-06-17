// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Regression test for the studies-list `starting → best` metric column.
 *
 * The list table renders the baseline (starting) metric beside the best metric
 * with a percent lift — the same `baseline_metric → best_metric (delta)` story
 * the study-detail digest panel shows — so a best score is read against the
 * baseline it improved on rather than in isolation. These tests render the
 * column's cell directly and assert the start, best, and lift fragments.
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { studiesColumns } from '@/components/studies/studies-table.column-config';
import { TooltipProvider } from '@/components/ui/tooltip';
import type { StudySummary } from '@/lib/api/studies';

function renderMetricCell(overrides: Partial<StudySummary>) {
  const column = studiesColumns.find((c) => c.id === 'best_metric');
  if (!column?.cell || typeof column.cell !== 'function') {
    throw new Error('best_metric column or its cell renderer not found');
  }
  const original: StudySummary = {
    id: 'study-1',
    name: 'demo',
    cluster_id: 'c1',
    status: 'completed',
    baseline_metric: 0.75,
    best_metric: 0.823,
    direction: 'maximize',
    created_at: '2026-06-17T00:00:00Z',
    completed_at: '2026-06-17T00:05:00Z',
    trial_count: 50,
    convergence_verdict: null,
    ...overrides,
  };
  const cell = column.cell as (ctx: { row: { original: StudySummary } }) => React.ReactNode;
  // The maximize ceiling badge embeds an InfoTooltip (Radix Tooltip), which
  // needs a TooltipProvider in the tree — matches the studies page wrapper.
  return render(<TooltipProvider delayDuration={0}>{cell({ row: { original } })}</TooltipProvider>);
}

describe('studies-table starting → best metric column', () => {
  it('renders baseline, best, and a positive lift for a maximize study', () => {
    renderMetricCell({ baseline_metric: 0.75, best_metric: 0.823 });
    expect(screen.getByText('0.750')).toBeInTheDocument();
    expect(screen.getByText('0.823')).toBeInTheDocument();
    // 0.823 vs 0.750 baseline = +9.7% lift.
    expect(screen.getByTestId('metric-lift-study-1')).toHaveTextContent('(+9.7%)');
  });

  it('shows a negative lift when best regressed below baseline (minimize win)', () => {
    // For a minimize objective the optimizer drives the metric DOWN, so best <
    // baseline is the win — deltaPct is purely arithmetic and reports the raw
    // signed change. 0.40 vs 0.50 baseline = -20.0%.
    renderMetricCell({ direction: 'minimize', baseline_metric: 0.5, best_metric: 0.4 });
    expect(screen.getByTestId('metric-lift-study-1')).toHaveTextContent('(-20.0%)');
  });

  it('renders an em dash for a missing baseline but still shows best + lift placeholder', () => {
    // Baseline is null when the baseline trial was skipped/failed or the study
    // predates feat_study_baseline_trial. The best value still renders; the
    // lift collapses to an em-dash since there is nothing to compare against.
    renderMetricCell({ baseline_metric: null, best_metric: 0.6 });
    expect(screen.getByText('0.600')).toBeInTheDocument();
    expect(screen.getByTestId('metric-lift-study-1')).toHaveTextContent('(—)');
  });

  it('renders a single em dash when there is no winner yet (best null)', () => {
    const { container } = renderMetricCell({ baseline_metric: 0.5, best_metric: null });
    expect(container.textContent).toContain('—');
    // No lift node when there is no best to compare — the early-return path.
    expect(screen.queryByTestId('metric-lift-study-1')).not.toBeInTheDocument();
  });

  it('reports "(new)" when the baseline is exactly zero', () => {
    renderMetricCell({ baseline_metric: 0, best_metric: 0.3 });
    expect(screen.getByTestId('metric-lift-study-1')).toHaveTextContent('(new)');
  });
});
