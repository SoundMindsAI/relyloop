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

  it('AC-8: hides the disclosure when hasClusters is true', () => {
    render(
      <StartHereChecklist
        hasClusters={true}
        hasQuerySetsWithJudgments={false}
        hasStudies={false}
      />,
    );
    expect(screen.queryByTestId('reset-demo-state-disclosure')).toBeNull();
  });

  it('AC-8: hides the disclosure when hasQuerySetsWithJudgments is true', () => {
    render(
      <StartHereChecklist
        hasClusters={false}
        hasQuerySetsWithJudgments={true}
        hasStudies={false}
      />,
    );
    expect(screen.queryByTestId('reset-demo-state-disclosure')).toBeNull();
  });

  it('AC-8: hides the disclosure when hasStudies is true', () => {
    render(
      <StartHereChecklist
        hasClusters={false}
        hasQuerySetsWithJudgments={false}
        hasStudies={true}
      />,
    );
    expect(screen.queryByTestId('reset-demo-state-disclosure')).toBeNull();
  });

  it('returns null entirely when all three signals are true (existing behavior)', () => {
    const { container } = render(
      <StartHereChecklist hasClusters={true} hasQuerySetsWithJudgments={true} hasStudies={true} />,
    );
    expect(container.firstChild).toBeNull();
  });
});
