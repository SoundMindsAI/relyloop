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

  it('AC-8: hides the disclosure when hasClusters is true (the operator already has a working cluster)', () => {
    render(
      <StartHereChecklist
        hasClusters={true}
        hasQuerySetsWithJudgments={false}
        hasStudies={false}
      />,
    );
    expect(screen.queryByTestId('reset-demo-state-disclosure')).toBeNull();
  });

  // bug_dashboard_reset_disclosure_gating_too_strict — the disclosure
  // previously hid whenever hasQuerySetsWithJudgments OR hasStudies was true,
  // even with no live clusters. That trapped operators whose stacks had
  // orphan data from earlier E2E runs but no usable clusters: the in-product
  // self-rescue affordance was hidden, forcing CLI knowledge of `make
  // seed-demo FORCE=1`. New behavior: disclosure renders whenever
  // hasClusters=false, regardless of orphan data.

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

  it('returns null entirely when all three signals are true (existing behavior)', () => {
    const { container } = render(
      <StartHereChecklist hasClusters={true} hasQuerySetsWithJudgments={true} hasStudies={true} />,
    );
    expect(container.firstChild).toBeNull();
  });
});
