// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * feat_study_convergence_indicator Story 4.1 — ConvergencePanel tests.
 *
 * Covers AC-11 / AC-12 / AC-13 / AC-13b / AC-13c / AC-20 (a11y label):
 *
 * - Verdict mapping (converged / still_improving / too_few_trials).
 * - <details> defaults: collapsed for converged, open for still_improving /
 *   too_few_trials.
 * - Null-state branching:
 *   - convergence=null && status in {queued, running} → "still running"
 *   - convergence=null && status terminal && trials.complete < 5 →
 *     "not enough trials yet"
 *   - convergence=null && status terminal && trials.complete >= 5 →
 *     "Verdict unavailable"
 * - aria-label string on the chart container.
 *
 * Recharts ResponsiveContainer measures parent dimensions via ResizeObserver;
 * jsdom doesn't ship ResizeObserver and reports width/height = 0, so the
 * chart's inner <svg> never renders. We assert the wrapper's existence by
 * data-testid (which IS rendered) and don't query for chart internals.
 */

import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';

import { ConvergencePanel } from '@/components/studies/convergence-panel';
import { TooltipProvider } from '@/components/ui/tooltip';
import type { components } from '@/lib/types';

type StudyConvergenceShape = components['schemas']['StudyConvergenceShape'];
type TrialsSummaryShape = components['schemas']['TrialsSummaryShape'];
type StudyStatusWire = components['schemas']['StudyDetail']['status'];

beforeAll(() => {
  // jsdom polyfill — Recharts ResponsiveContainer calls ResizeObserver during
  // initial measure. Without this the rendering thread throws and the panel
  // unmounts.
  if (typeof globalThis.ResizeObserver === 'undefined') {
    globalThis.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    } as unknown as typeof ResizeObserver;
  }
});

afterEach(cleanup);

function makeCurve(length: number, plateau = 0.5): StudyConvergenceShape['best_so_far_curve'] {
  return Array.from({ length }, (_v, i) => ({
    trial_number: i,
    best_so_far: plateau,
  }));
}

function makeConvergence(overrides: Partial<StudyConvergenceShape> = {}): StudyConvergenceShape {
  return {
    verdict: 'converged',
    direction: 'maximize',
    window_size: 20,
    epsilon: 0.005,
    warmup_floor: 50,
    total_complete_trials: 275,
    improvement_in_window: 0.0008,
    best_so_far_curve: makeCurve(275),
    ...overrides,
  };
}

function makeTrialsSummary(overrides: Partial<TrialsSummaryShape> = {}): TrialsSummaryShape {
  return {
    total: 275,
    complete: 275,
    failed: 0,
    pruned: 0,
    best_primary_metric: 0.5,
    ...overrides,
  };
}

function renderPanel(
  convergence: StudyConvergenceShape | null,
  studyStatus: StudyStatusWire = 'completed',
  trialsSummary: TrialsSummaryShape = makeTrialsSummary(),
) {
  return render(
    <TooltipProvider>
      <ConvergencePanel
        convergence={convergence}
        studyStatus={studyStatus}
        trialsSummary={trialsSummary}
      />
    </TooltipProvider>,
  );
}

describe('ConvergencePanel — verdict branches', () => {
  it('AC-11: converged → success badge, details collapsed, curve mounted', () => {
    renderPanel(makeConvergence({ verdict: 'converged' }));
    const badge = screen.getByTestId('cs-convergence-verdict');
    expect(badge).toHaveTextContent('Converged');
    expect(badge).toHaveAttribute('data-verdict', 'converged');
    expect(badge).toHaveAttribute('aria-label', 'Converged');
    const details = screen.getByTestId('convergence-curve-details');
    // <details> has no `open` attr by default → DOM property is false.
    expect((details as HTMLDetailsElement).open).toBe(false);
    // Curve container exists even when collapsed (renders inside details body).
    expect(screen.getByTestId('convergence-curve')).toBeInTheDocument();
  });

  it('AC-12: still_improving → warning badge, details open by default', () => {
    renderPanel(makeConvergence({ verdict: 'still_improving' }));
    const badge = screen.getByTestId('cs-convergence-verdict');
    expect(badge).toHaveTextContent('Still improving when it stopped');
    expect(badge).toHaveAttribute('data-verdict', 'still_improving');
    const details = screen.getByTestId('convergence-curve-details');
    expect((details as HTMLDetailsElement).open).toBe(true);
  });

  it('too_few_trials → warning badge, details open by default', () => {
    renderPanel(makeConvergence({ verdict: 'too_few_trials' }));
    const badge = screen.getByTestId('cs-convergence-verdict');
    expect(badge).toHaveTextContent('Too few trials to tell');
    expect(badge).toHaveAttribute('data-verdict', 'too_few_trials');
    const details = screen.getByTestId('convergence-curve-details');
    expect((details as HTMLDetailsElement).open).toBe(true);
  });
});

describe('ConvergencePanel — AC-20 aria-label', () => {
  it('renders the exact AC-20 aria-label format', () => {
    renderPanel(
      makeConvergence({
        verdict: 'converged',
        total_complete_trials: 275,
        window_size: 20,
        improvement_in_window: 0.0008,
      }),
    );
    const curve = screen.getByTestId('convergence-curve');
    expect(curve).toHaveAttribute(
      'aria-label',
      'Convergence curve: converged after 275 trials; window 20; improvement 0.0008',
    );
  });
});

describe('ConvergencePanel — null-state branches', () => {
  it('AC-13: convergence=null + running → "Verdict pending — still running", no chart', () => {
    renderPanel(null, 'running', makeTrialsSummary({ complete: 80 }));
    const badge = screen.getByTestId('cs-convergence-verdict');
    expect(badge).toHaveTextContent('Verdict pending — still running');
    expect(badge).toHaveAttribute('data-null-reason', 'still_running');
    // No chart container mounted in the null path.
    expect(screen.queryByTestId('convergence-curve')).not.toBeInTheDocument();
  });

  it('AC-13: convergence=null + queued → "Verdict pending — still running"', () => {
    renderPanel(null, 'queued', makeTrialsSummary({ complete: 0 }));
    const badge = screen.getByTestId('cs-convergence-verdict');
    expect(badge).toHaveTextContent('Verdict pending — still running');
  });

  it('AC-13b: convergence=null + completed + complete<5 → "not enough trials yet"', () => {
    renderPanel(null, 'completed', makeTrialsSummary({ complete: 4 }));
    const badge = screen.getByTestId('cs-convergence-verdict');
    expect(badge).toHaveTextContent('Verdict pending — not enough trials yet');
    expect(badge).toHaveAttribute('data-null-reason', 'not_enough_trials');
  });

  it('AC-13c: convergence=null + completed + complete>=5 → "Verdict unavailable"', () => {
    renderPanel(null, 'completed', makeTrialsSummary({ complete: 100 }));
    const badge = screen.getByTestId('cs-convergence-verdict');
    expect(badge).toHaveTextContent('Verdict unavailable');
    expect(badge).toHaveAttribute('data-null-reason', 'unavailable');
  });

  it('AC-13c: convergence=null + cancelled + complete>=5 → "Verdict unavailable"', () => {
    renderPanel(null, 'cancelled', makeTrialsSummary({ complete: 80 }));
    expect(screen.getByTestId('cs-convergence-verdict')).toHaveTextContent('Verdict unavailable');
  });
});

describe('ConvergencePanel — improvement summary line', () => {
  it('renders the improvement-in-window text only when populated', () => {
    renderPanel(
      makeConvergence({
        improvement_in_window: 0.0123,
        window_size: 20,
      }),
    );
    expect(screen.getByText(/Improved by 0\.0123 in the last 20 trials/)).toBeInTheDocument();
  });

  it('does NOT render the improvement summary on the null path', () => {
    renderPanel(null, 'completed', makeTrialsSummary({ complete: 100 }));
    expect(screen.queryByText(/Improved by/)).not.toBeInTheDocument();
  });
});
