// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * feat_pr_metric_confidence Story 2.2 — ConfidencePanel component tests.
 *
 * 12 cases covering AC-13 component layer + FR-7 graceful-degradation
 * branches. The shape mirrors the FastAPI ConfidenceShape exposed on
 * StudyDetail; the component lives at
 * `ui/src/components/studies/confidence-panel.tsx`.
 */

import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';

import { ConfidencePanel } from '@/components/studies/confidence-panel';
import { TooltipProvider } from '@/components/ui/tooltip';
import type { components } from '@/lib/types';

type ConfidenceShape = components['schemas']['ConfidenceShape'];

function makeConfidence(overrides: Partial<ConfidenceShape> = {}): ConfidenceShape {
  return {
    headline: { metric: 'ndcg', value: 0.84, k: 10, n_queries: 20 },
    ci_95: { low: 0.78, high: 0.89, method: 'bootstrap_n1000', n_samples: 20 },
    runner_up_gap: {
      value: 0.002,
      classification: 'robust_plateau',
      top10_within: 0.004,
      runner_up_metric: 0.838,
    },
    late_trial_stddev: { value: 0.012, window_size: 20, min_window_required: 10 },
    convergence: { best_at_trial: 387, total_trials: 1000, regime: 'early_held' },
    per_query_outcomes: {
      improved: 14,
      unchanged: 4,
      regressed: 2,
      comparison_against: 'runner_up',
      top_regressors: [
        {
          query_id: 'q1',
          query_text: 'vintage acoustic guitar',
          winner_score: 0.41,
          comparison_score: 0.92,
          delta: -0.51,
        },
        {
          query_id: 'q2',
          query_text: 'leather wallet',
          winner_score: 0.55,
          comparison_score: 0.78,
          delta: -0.23,
        },
      ],
      top_improvers: [
        {
          query_id: 'q3',
          query_text: 'wireless headphones',
          winner_score: 0.88,
          comparison_score: 0.55,
          delta: 0.33,
        },
        {
          query_id: 'q4',
          query_text: 'running shoes',
          winner_score: 0.79,
          comparison_score: 0.61,
          delta: 0.18,
        },
      ],
    },
    ...overrides,
  };
}

function mount(confidence: ConfidenceShape | null | undefined) {
  return render(
    <TooltipProvider>
      <ConfidencePanel confidence={confidence} />
    </TooltipProvider>,
  );
}

afterEach(() => {
  cleanup();
});

describe('<ConfidencePanel>', () => {
  it('renders nothing when confidence is null (whole-object null → AC-12 / AC-3a)', () => {
    const { container } = mount(null);
    expect(container.firstChild).toBeNull();
  });

  it('renders nothing when confidence is undefined (still-running study)', () => {
    const { container } = mount(undefined);
    expect(container.firstChild).toBeNull();
  });

  it('renders headline metric@k + value + CI band when ci_95 is present', () => {
    mount(makeConfidence());
    const panel = screen.getByTestId('confidence-panel');
    expect(within(panel).getByText('Confidence')).toBeTruthy();
    const headline = within(panel).getByTestId('confidence-headline');
    expect(headline.textContent).toContain('NDCG@10');
    expect(headline.textContent).toContain('0.840');
    const ci = within(panel).getByTestId('confidence-ci');
    expect(ci.textContent).toContain('95% CI 0.780–0.890');
    expect(ci.textContent).toContain('N=20 queries');
  });

  it('omits the CI band when ci_95 is null (AC-15: <5 queries)', () => {
    mount(makeConfidence({ ci_95: null }));
    expect(screen.queryByTestId('confidence-ci')).toBeNull();
    // Headline value still renders.
    const headline = screen.getByTestId('confidence-headline');
    expect(headline.textContent).toContain('0.840');
  });

  it('renders the per-query outcome chips with the right counts + comparison label', () => {
    mount(makeConfidence());
    expect(screen.getByTestId('outcome-improved').textContent).toBe('14 Improved');
    expect(screen.getByTestId('outcome-unchanged').textContent).toBe('4 Unchanged');
    expect(screen.getByTestId('outcome-regressed').textContent).toBe('2 Regressed');
    // "vs runner-up" — note hyphen, not underscore.
    expect(screen.getByTestId('confidence-outcomes').textContent).toContain('vs runner-up');
  });

  it('renders the named regressors table (capped) with query_text + scores + delta', () => {
    mount(makeConfidence());
    const table = screen.getByTestId('confidence-regressors');
    expect(within(table).getByText('vintage acoustic guitar')).toBeTruthy();
    expect(within(table).getByText('leather wallet')).toBeTruthy();
    expect(within(table).getByText('0.410')).toBeTruthy();
    expect(within(table).getByText('0.920')).toBeTruthy();
    expect(within(table).getByText('-0.510')).toBeTruthy();
  });

  it('renders the named improvers table with query_text + scores + positive delta', () => {
    mount(makeConfidence());
    const table = screen.getByTestId('confidence-improvers');
    expect(within(table).getByText('wireless headphones')).toBeTruthy();
    expect(within(table).getByText('running shoes')).toBeTruthy();
    expect(within(table).getByText('0.880')).toBeTruthy();
    expect(within(table).getByText('+0.330')).toBeTruthy();
    expect(within(table).getByText('+0.180')).toBeTruthy();
  });

  it('omits the named-improvers table when improved === 0', () => {
    mount(
      makeConfidence({
        per_query_outcomes: {
          improved: 0,
          unchanged: 18,
          regressed: 2,
          comparison_against: 'runner_up',
          top_regressors: [
            {
              query_id: 'q1',
              query_text: 'q1 text',
              winner_score: 0.41,
              comparison_score: 0.92,
              delta: -0.51,
            },
          ],
          top_improvers: [],
        },
      }),
    );
    expect(screen.queryByTestId('confidence-improvers')).toBeNull();
    expect(screen.getByTestId('outcome-improved').textContent).toBe('0 Improved');
  });

  it('omits the named-regressors table when regressed === 0 (AC-3 mirror)', () => {
    mount(
      makeConfidence({
        per_query_outcomes: {
          improved: 18,
          unchanged: 2,
          regressed: 0,
          comparison_against: 'runner_up',
          top_regressors: [],
          top_improvers: [],
        },
      }),
    );
    expect(screen.queryByTestId('confidence-regressors')).toBeNull();
    // The chip row + comparison label still render.
    expect(screen.getByTestId('outcome-regressed').textContent).toBe('0 Regressed');
  });

  it('switches the comparison label to "vs baseline" when comparison_against === "baseline" (Phase 2 future)', () => {
    mount(
      makeConfidence({
        per_query_outcomes: {
          improved: 14,
          unchanged: 4,
          regressed: 2,
          comparison_against: 'baseline',
          top_regressors: [
            {
              query_id: 'q1',
              query_text: 'q1 text',
              winner_score: 0.41,
              comparison_score: 0.92,
              delta: -0.51,
            },
          ],
          top_improvers: [],
        },
      }),
    );
    expect(screen.getByTestId('confidence-outcomes').textContent).toContain('vs baseline');
    const table = screen.getByTestId('confidence-regressors');
    expect(within(table).getByText('vs baseline')).toBeTruthy();
  });

  it('renders the runner-up gap callout with the "Robust plateau" badge label', () => {
    mount(makeConfidence());
    const callout = screen.getByTestId('callout-runner-up-gap');
    expect(callout.textContent).toContain('0.002');
    expect(callout.textContent).toContain('Robust plateau');
  });

  it('renders the runner-up gap callout with the "Sharp peak" badge label', () => {
    mount(
      makeConfidence({
        runner_up_gap: {
          value: 0.08,
          classification: 'sharp_peak',
          top10_within: 0.08,
          runner_up_metric: 0.76,
        },
      }),
    );
    const callout = screen.getByTestId('callout-runner-up-gap');
    expect(callout.textContent).toContain('Sharp peak');
  });

  it('renders the convergence callout with the regime label + "best at trial X of Y"', () => {
    mount(makeConfidence());
    const callout = screen.getByTestId('callout-convergence');
    expect(callout.textContent).toContain('Early-and-held');
    expect(callout.textContent).toContain('best at trial 387 of 1000');
  });

  it('shows "Late-rising" for the late-rising regime (AC-9 component-layer mirror)', () => {
    mount(
      makeConfidence({
        convergence: { best_at_trial: 950, total_trials: 1000, regime: 'late_rising' },
      }),
    );
    expect(screen.getByTestId('callout-convergence').textContent).toContain('Late-rising');
  });

  it('wires the 6 InfoTooltip glossary triggers per spec §11 (FR-5c tooltip inventory)', () => {
    // Story 2.2 DoD: each contextual-help anchor on the panel must mount
    // an `<InfoTooltip>` resolving against the matching glossary key.
    // The primitive emits `tooltip-trigger-<glossary-key>` test IDs.
    // We assert each of the six confidence-prefixed keys mounts at least
    // one trigger so a future refactor that drops a label can't silently
    // strip the tooltip surface.
    mount(makeConfidence());
    const expectedKeys = [
      'confidence.ci_95',
      'confidence.per_query_outcomes',
      'confidence.comparison_against',
      'confidence.runner_up_gap',
      'confidence.late_trial_stddev',
      'confidence.convergence_regime',
    ];
    for (const key of expectedKeys) {
      expect(
        screen.getByTestId(`tooltip-trigger-${key}`),
        `missing InfoTooltip for ${key}`,
      ).toBeTruthy();
    }
  });

  it('renders partial shape gracefully — ci_95 + per_query_outcomes null, aggregate signals only (AC-3)', () => {
    mount(
      makeConfidence({
        ci_95: null,
        per_query_outcomes: null,
        headline: { metric: 'ndcg', value: 0.84, k: 10, n_queries: null },
      }),
    );
    // Heading + headline still render.
    expect(screen.getByTestId('confidence-headline').textContent).toContain('NDCG@10');
    // CI band absent.
    expect(screen.queryByTestId('confidence-ci')).toBeNull();
    // Per-query block absent.
    expect(screen.queryByTestId('confidence-outcomes')).toBeNull();
    expect(screen.queryByTestId('confidence-regressors')).toBeNull();
    // Aggregate callouts still render.
    expect(screen.getByTestId('callout-runner-up-gap')).toBeTruthy();
    expect(screen.getByTestId('callout-late-trial-stddev')).toBeTruthy();
    expect(screen.getByTestId('callout-convergence')).toBeTruthy();
  });
});
