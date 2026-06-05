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
  source_breakdown: { llm: 10, human: 2, click: 0 },
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

function renderWithBreakdown(breakdown: { llm: number; human: number; click: number }) {
  return render(
    <TooltipProvider>
      <JudgmentListHeader list={{ ...BASE_LIST, source_breakdown: breakdown }} />
    </TooltipProvider>,
  );
}

describe('<JudgmentListHeader /> — source breakdown (click bucket)', () => {
  it('AC-1: renders all three terms when click is non-zero', () => {
    renderWithBreakdown({ llm: 0, human: 2, click: 5 });
    expect(screen.getByTestId('header-breakdown')).toHaveTextContent('0 / 2 / 5');
  });

  it('AC-2: renders a zero click term as the third value', () => {
    renderWithBreakdown({ llm: 10, human: 2, click: 0 });
    expect(screen.getByTestId('header-breakdown')).toHaveTextContent('10 / 2 / 0');
  });

  it('AC-3: preserves the header-breakdown testid', () => {
    renderWithBreakdown({ llm: 1, human: 1, click: 1 });
    expect(screen.getByTestId('header-breakdown')).toBeInTheDocument();
  });

  it('FR-2: the breakdown label reads "LLM / Human / Clicks"', () => {
    renderWithBreakdown({ llm: 1, human: 1, click: 1 });
    expect(screen.getByText('LLM / Human / Clicks')).toBeInTheDocument();
  });

  it('AC-5: locale-formats each term (runtime-computed expected)', () => {
    renderWithBreakdown({ llm: 1234, human: 0, click: 5678 });
    const expected = `${(1234).toLocaleString()} / ${(0).toLocaleString()} / ${(5678).toLocaleString()}`;
    expect(screen.getByTestId('header-breakdown')).toHaveTextContent(expected);
  });

  it('FR-4: the click-bucket glossary help is reachable via the label tooltip', () => {
    renderWithBreakdown({ llm: 1, human: 1, click: 1 });
    // InfoTooltip (tooltip mode) renders a glossary-keyed trigger button.
    expect(screen.getByTestId('tooltip-trigger-judgment.source.click')).toBeInTheDocument();
  });
});

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
