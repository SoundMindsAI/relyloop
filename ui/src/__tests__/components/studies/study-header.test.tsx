// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Story 3.2 / FR-7 surface #4 — three-branch chip gating on StudyHeader.
 * The component is presentational; the page-level wrapper resolves
 * cluster + judgment-list and computes the chip-visibility boolean.
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { StudyHeader } from '@/components/studies/study-header';
import { TooltipProvider } from '@/components/ui/tooltip';
import type { StudyDetail } from '@/lib/api/studies';

function makeStudy(overrides: Partial<StudyDetail> = {}): StudyDetail {
  return {
    id: 'study-1',
    name: 'demo study (UBI)',
    cluster_id: 'cluster-1',
    target: 'products',
    template_id: 'template-1',
    query_set_id: 'qs-1',
    judgment_list_id: 'jl-ubi-1',
    search_space: { params: {} },
    objective: { metric: 'ndcg', k: 10, direction: 'maximize' },
    config: {},
    status: 'completed',
    failed_reason: null,
    optuna_study_name: 'study-1',
    parent_study_id: null,
    baseline_metric: null,
    best_metric: 0.5,
    best_trial_id: null,
    created_at: '2026-05-23T10:00:00Z',
    started_at: '2026-05-23T10:00:01Z',
    completed_at: '2026-05-23T10:30:00Z',
    trials_summary: {
      total: 5,
      complete: 5,
      failed: 0,
      pruned: 0,
      best_primary_metric: 0.5,
    },
    confidence: null,
    ...overrides,
  } as StudyDetail;
}

function renderWith({ showSyntheticUbiChip }: { showSyntheticUbiChip?: boolean }) {
  return render(
    <TooltipProvider>
      <StudyHeader study={makeStudy()} showSyntheticUbiChip={showSyntheticUbiChip} />
    </TooltipProvider>,
  );
}

describe('<StudyHeader /> — synthetic-data chip (FR-7 surface #4)', () => {
  it('renders the chip when showSyntheticUbiChip is true', () => {
    // Branch (a): synthetic-UBI demo cluster + UBI judgment list → chip.
    renderWith({ showSyntheticUbiChip: true });
    expect(screen.getByTestId('demo-badge-synthetic-ubi')).toBeInTheDocument();
  });

  it('does NOT render the chip when showSyntheticUbiChip is false', () => {
    // Branch (b): demo cluster without synthetic UBI (news-search-staging)
    // OR a UBI study on a real production cluster → no chip.
    renderWith({ showSyntheticUbiChip: false });
    expect(screen.queryByTestId('demo-badge-synthetic-ubi')).not.toBeInTheDocument();
  });

  it('does NOT render the chip when the prop is omitted (default false)', () => {
    // Branch (c): non-UBI study (LLM judgment list) — the wrapper never
    // sets the prop, so the default false branch must hide the chip.
    renderWith({});
    expect(screen.queryByTestId('demo-badge-synthetic-ubi')).not.toBeInTheDocument();
  });
});
