// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ConvergenceOverlay } from '@/components/studies/comparison/convergence-overlay';

// Recharts' ResponsiveContainer needs a sized parent; stub it so the chart
// renders deterministically in jsdom.
vi.mock('recharts', async (orig) => {
  const actual = (await orig()) as Record<string, unknown>;
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div style={{ width: 500, height: 240 }}>{children}</div>
    ),
  };
});

describe('ConvergenceOverlay (FR-7)', () => {
  it('renders the chart when at least one curve has data', () => {
    render(
      <ConvergenceOverlay
        llmCurve={[
          { trial_number: 0, best_so_far: 0.3 },
          { trial_number: 1, best_so_far: 0.5 },
        ]}
        ubiCurve={[{ trial_number: 0, best_so_far: 0.4 }]}
      />,
    );
    expect(screen.getByTestId('compare-convergence-chart')).toBeInTheDocument();
    expect(screen.queryByTestId('compare-convergence-empty')).toBeNull();
  });

  it('empty state when neither side has a curve', () => {
    render(<ConvergenceOverlay llmCurve={null} ubiCurve={[]} />);
    expect(screen.getByTestId('compare-convergence-empty')).toBeInTheDocument();
  });
});
