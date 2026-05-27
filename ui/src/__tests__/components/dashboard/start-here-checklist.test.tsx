/**
 * Vitest spec for ``<StartHereChecklist />`` — covers the new
 * "Reset to demo state" disclosure introduced by
 * feat_home_demo_reseed_endpoint (FR-6 / AC-7 + AC-8).
 *
 * Existing checklist behavior (the 3-step <ol>, return-null-when-all-done
 * rule) is unchanged and not retested here.
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

// Stub the reset button so this spec stays focused on the disclosure
// gate. The button itself has its own spec.
vi.mock('@/components/dashboard/reset-demo-state-button', () => ({
  ResetDemoStateButton: () => <button data-testid="reset-demo-state-trigger">Reset</button>,
}));

import { StartHereChecklist } from '@/components/dashboard/start-here-checklist';

describe('<StartHereChecklist /> — reset-demo disclosure', () => {
  it('AC-7: renders the disclosure when all three first-run signals are false', () => {
    render(
      <StartHereChecklist
        hasClusters={false}
        hasQuerySetsWithJudgments={false}
        hasStudies={false}
      />,
    );
    const disclosure = screen.getByTestId('reset-demo-state-disclosure');
    expect(disclosure).toBeInTheDocument();
    // Lowercase, casual summary text per spec §11.
    expect(disclosure.querySelector('summary')?.textContent).toBe(
      'or skip ahead — reset to demo state',
    );
  });

  it('renders the disclosure even when hasClusters is true (bug_demo_reseed_fake_metric_regression follow-up — operators need to re-trigger reseed to replace fake-metric studies)', () => {
    // Previously: disclosure was hidden when hasClusters was true on the
    // theory that an operator with a working cluster doesn't need the
    // reseed affordance. That assumption broke once the legacy sync
    // reseed produced fake-metric demo studies — the operator's cluster
    // existed but they needed to re-reseed to get real metrics. The
    // disclosure is collapsed by default + the dialog's confirmation
    // copy is loud, so unconditional rendering is safe.
    render(
      <StartHereChecklist
        hasClusters={true}
        hasQuerySetsWithJudgments={false}
        hasStudies={false}
      />,
    );
    expect(screen.getByTestId('reset-demo-state-disclosure')).toBeInTheDocument();
  });

  it('renders the disclosure when hasClusters=false even if hasQuerySetsWithJudgments is true (orphan data state)', () => {
    render(
      <StartHereChecklist
        hasClusters={false}
        hasQuerySetsWithJudgments={true}
        hasStudies={false}
      />,
    );
    expect(screen.getByTestId('reset-demo-state-disclosure')).toBeInTheDocument();
  });

  it('renders the disclosure when hasClusters=false even if hasStudies is true (orphan data state)', () => {
    render(
      <StartHereChecklist
        hasClusters={false}
        hasQuerySetsWithJudgments={false}
        hasStudies={true}
      />,
    );
    expect(screen.getByTestId('reset-demo-state-disclosure')).toBeInTheDocument();
  });

  it('renders the disclosure when hasClusters=false even with both orphan data signals true (operator session 2026-05-26)', () => {
    // The exact stuck state that surfaced this bug: no live clusters but
    // both orphan studies and orphan query_sets sitting in the DB.
    render(
      <StartHereChecklist hasClusters={false} hasQuerySetsWithJudgments={true} hasStudies={true} />,
    );
    expect(screen.getByTestId('reset-demo-state-disclosure')).toBeInTheDocument();
  });

  it('renders the disclosure (and only the disclosure) when all three signals are true — fully-seeded fast-path', () => {
    // Per bug_demo_reseed_fake_metric_regression follow-up: once the
    // operator has a complete demo state, the checklist itself hides
    // (nothing to do) but the reset affordance stays reachable so they
    // can re-reseed (e.g., to replace legacy fake-metric studies).
    render(
      <StartHereChecklist hasClusters={true} hasQuerySetsWithJudgments={true} hasStudies={true} />,
    );
    // The checklist's main testid is absent (operator-facing first-run
    // CTAs hidden)…
    expect(screen.queryByTestId('start-here-checklist')).toBeNull();
    // …but the fully-seeded fast-path card + disclosure are present.
    expect(screen.getByTestId('start-here-checklist-fully-seeded')).toBeInTheDocument();
    expect(screen.getByTestId('reset-demo-state-disclosure')).toBeInTheDocument();
  });
});
