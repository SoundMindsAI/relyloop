// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * feat_study_clone_from_previous Story 2.2 — FR-2 / AC-9 regression assertion.
 *
 * Per spec FR-2 and D-7: the digest panel intentionally does NOT expose
 * a "Clone study" button. Clone is reachable only from the study-detail
 * action bar (StudyActionBar). The digest panel exposes "Run this
 * followup" (the proposal-followup path), which is a different lineage
 * axis.
 *
 * This test guards against a future edit accidentally adding a
 * `data-testid="clone-study"` or visible "Clone study" affordance to
 * the digest panel.
 */

import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';

import { DigestPanel } from '@/components/studies/digest-panel';
import { TooltipProvider } from '@/components/ui/tooltip';
import type { DigestResponse } from '@/lib/api/digests';

function wrap(node: ReactNode) {
  return render(<TooltipProvider delayDuration={0}>{node}</TooltipProvider>);
}

const MINIMAL_DIGEST: DigestResponse = {
  id: 'd1',
  study_id: 'st1',
  narrative: 'Tuning lifted ndcg@10 from 0.41 to 0.52.',
  // Empty parameter_importance routes ParameterImportanceChart through its
  // empty-state branch and bypasses Recharts (whose ResponsiveContainer needs
  // a ResizeObserver polyfill in jsdom). This test is about the absence of a
  // Clone button — the chart's render path is incidental.
  parameter_importance: {},
  recommended_config: {},
  suggested_followups: [],
  generated_by: 'openai:gpt-4o-2024-08-06',
  generated_at: '2026-05-24T00:00:00Z',
};

describe('DigestPanel — FR-2 regression (no Clone button on the digest panel)', () => {
  it('does NOT render an element with data-testid="clone-study"', () => {
    wrap(
      <DigestPanel
        digest={MINIMAL_DIGEST}
        baselineMetric={0.41}
        bestMetric={0.52}
        pendingProposal={null}
      />,
    );
    expect(screen.queryByTestId('clone-study')).toBeNull();
  });

  it('does NOT render any visible text matching /Clone study/i', () => {
    wrap(
      <DigestPanel
        digest={MINIMAL_DIGEST}
        baselineMetric={0.41}
        bestMetric={0.52}
        pendingProposal={null}
      />,
    );
    expect(screen.queryByText(/Clone study/i)).toBeNull();
  });
});
