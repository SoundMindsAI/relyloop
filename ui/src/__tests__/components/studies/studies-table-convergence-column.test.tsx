// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Tests for the studies-list Trials + Convergence columns
 * (feat_studies_convergence_visibility Story 1.2 / FR-4).
 *
 * Verifies:
 * - the trial_count cell renders the numeric count;
 * - the convergence badge renders the correct compact label/variant for
 *   each verdict, sourced from CONVERGENCE_VERDICT_VALUES;
 * - a null verdict renders an em-dash (no badge), matching the detail
 *   panel's null-state behavior.
 */
import { render, screen } from '@testing-library/react';
import { type ReactNode } from 'react';
import { describe, expect, it } from 'vitest';

import { studiesColumns } from '@/components/studies/studies-table.column-config';
import { TooltipProvider } from '@/components/ui/tooltip';
import type { StudySummary } from '@/lib/api/studies';
import { CONVERGENCE_VERDICT_VALUES } from '@/lib/enums';

function baseStudy(overrides: Partial<StudySummary>): StudySummary {
  return {
    id: 'study-1',
    name: 'demo',
    cluster_id: 'c1',
    status: 'completed',
    best_metric: 0.8,
    direction: 'maximize',
    created_at: '2026-05-29T00:00:00Z',
    completed_at: '2026-05-29T00:05:00Z',
    trial_count: 50,
    convergence_verdict: null,
    ...overrides,
  };
}

function renderCell(columnId: string, original: StudySummary) {
  const column = studiesColumns.find((c) => c.id === columnId);
  if (!column?.cell || typeof column.cell !== 'function') {
    throw new Error(`${columnId} column or its cell renderer not found`);
  }
  const cell = column.cell as (ctx: { row: { original: StudySummary } }) => ReactNode;
  return render(<TooltipProvider delayDuration={0}>{cell({ row: { original } })}</TooltipProvider>);
}

describe('studies-table Trials column', () => {
  it('renders the non-baseline trial count', () => {
    renderCell('trial_count', baseStudy({ trial_count: 37 }));
    expect(screen.getByText('37')).toBeInTheDocument();
  });

  it('renders zero for a queued study', () => {
    renderCell('trial_count', baseStudy({ status: 'queued', trial_count: 0 }));
    expect(screen.getByText('0')).toBeInTheDocument();
  });
});

describe('studies-table Convergence column', () => {
  const cases: Array<[StudySummary['convergence_verdict'], string]> = [
    ['converged', 'Converged'],
    ['still_improving', 'Improving'],
    ['too_few_trials', 'Too few trials'],
  ];

  it.each(cases)('renders the %s verdict as "%s"', (verdict, label) => {
    const { container } = renderCell(
      'convergence_verdict',
      baseStudy({ convergence_verdict: verdict }),
    );
    expect(screen.getByText(label)).toBeInTheDocument();
    // The data-verdict attribute carries the wire value for downstream
    // assertions / E2E hooks.
    expect(container.querySelector(`[data-verdict="${verdict}"]`)).not.toBeNull();
  });

  it('renders an em-dash for a null verdict (no badge)', () => {
    const { container } = renderCell(
      'convergence_verdict',
      baseStudy({ convergence_verdict: null }),
    );
    expect(screen.getByText('—')).toBeInTheDocument();
    expect(container.querySelector('[data-verdict]')).toBeNull();
  });

  it('has a label for every backend verdict literal (no missing badge)', () => {
    // Source-of-truth guard: every value in CONVERGENCE_VERDICT_VALUES must
    // render a non-em-dash badge. A backend verdict added without a label
    // here would slip through TypeScript only if the `satisfies` map drifted;
    // this is the runtime backstop.
    for (const verdict of CONVERGENCE_VERDICT_VALUES) {
      const { container, unmount } = renderCell(
        'convergence_verdict',
        baseStudy({ convergence_verdict: verdict }),
      );
      expect(container.querySelector(`[data-verdict="${verdict}"]`)).not.toBeNull();
      unmount();
    }
  });

  it('falls back to an em-dash for an unmapped verdict (forward-compat guard)', () => {
    // Regression test for the Gemini PR #438 finding (accepted): a newer
    // backend could emit a convergence_verdict this frontend snapshot doesn't
    // map (rolling deploy). The cast simulates that out-of-union runtime value
    // — TypeScript would never let it through the typed path, but the wire can.
    // The cell must render the same em-dash as the null state, NOT crash on
    // `badge.variant`.
    const unknown = 'diverged' as StudySummary['convergence_verdict'];
    const { container } = renderCell(
      'convergence_verdict',
      baseStudy({ convergence_verdict: unknown }),
    );
    expect(screen.getByText('—')).toBeInTheDocument();
    // No badge rendered for the unmapped value.
    expect(container.querySelector('[data-verdict]')).toBeNull();
  });
});
