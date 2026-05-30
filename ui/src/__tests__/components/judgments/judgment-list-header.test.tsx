// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Story 3.2 / FR-7 surface #2 — three-branch chip gating on
 * JudgmentListHeader. The component is presentational; the page-level
 * wrapper does the synthetic-UBI decision and forwards a boolean.
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { JudgmentListHeader } from '@/components/judgments/judgment-list-header';
import { TooltipProvider } from '@/components/ui/tooltip';
import type { JudgmentListDetail } from '@/lib/api/judgments';

const BASE_LIST: JudgmentListDetail = {
  id: 'list-1',
  name: 'demo list',
  description: null,
  query_set_id: 'qs-1',
  cluster_id: 'c-1',
  target: 'products',
  current_template_id: null,
  rubric: 'rate 0-3',
  status: 'complete',
  failed_reason: null,
  judgment_count: 12,
  source_breakdown: { llm: 10, human: 2 },
  calibration: null,
  created_at: '2026-05-12T00:00:00Z',
  // generation_params is JSONB on the backend and the FR-7 page-level
  // wrapper reads it to gate the chip; the header itself only consumes
  // the precomputed boolean.
  generation_params: null,
};

function renderWith({ showSyntheticUbiChip }: { showSyntheticUbiChip?: boolean }) {
  return render(
    <TooltipProvider>
      <JudgmentListHeader list={BASE_LIST} showSyntheticUbiChip={showSyntheticUbiChip} />
    </TooltipProvider>,
  );
}

describe('<JudgmentListHeader /> — synthetic-data chip (FR-7 surface #2)', () => {
  it('renders the chip when showSyntheticUbiChip is true', () => {
    // Branch (a): synthetic-UBI demo cluster + UBI list → chip.
    renderWith({ showSyntheticUbiChip: true });
    expect(screen.getByTestId('demo-badge-synthetic-ubi')).toBeInTheDocument();
  });

  it('does NOT render the chip when showSyntheticUbiChip is false', () => {
    // Branch (b): demo cluster without synthetic UBI
    // (news-search-staging) → no chip even on a UBI list.
    renderWith({ showSyntheticUbiChip: false });
    expect(screen.queryByTestId('demo-badge-synthetic-ubi')).not.toBeInTheDocument();
  });

  it('does NOT render the chip when the prop is omitted (default false)', () => {
    // Branch (c): non-demo cluster — caller never sets the prop, so the
    // default false branch must hide the chip.
    renderWith({});
    expect(screen.queryByTestId('demo-badge-synthetic-ubi')).not.toBeInTheDocument();
  });
});
