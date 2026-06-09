// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * feat_query_normalizer_typed_pipeline FR-6 / AC-9 — the typed-pipeline builder
 * row. Covers: (a) the six step toggles are sourced from NORMALIZER_STEP_VALUES
 * with glossary labels; (b) selecting [lowercase, trim] emits steps in
 * STEP_ORDER; (c) the per-row cardinality preview reads 4 (=2²); (d) an
 * empty-steps row is flagged incomplete (and cleared once a step is picked).
 */

import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import type { ReactNode } from 'react';

import { RowCardinality } from '@/components/studies/search-space-builder/cardinality';
import { RowNormalizerPipeline } from '@/components/studies/search-space-builder/row-normalizer-pipeline';
import { TooltipProvider } from '@/components/ui/tooltip';
import { NORMALIZER_STEP_GLOSSARY_KEYS, NORMALIZER_STEP_VALUES } from '@/lib/enums';
import { glossary } from '@/lib/glossary';
import { estimateParamCardinality } from '@/lib/search-space-defaults';

function wrap(node: ReactNode) {
  return render(<TooltipProvider delayDuration={0}>{node}</TooltipProvider>);
}

describe('RowNormalizerPipeline (AC-9)', () => {
  it('(a) renders all six steps from NORMALIZER_STEP_VALUES with glossary labels', () => {
    wrap(<RowNormalizerPipeline paramName="query_normalizer" steps={[]} onChange={() => {}} />);
    for (const step of NORMALIZER_STEP_VALUES) {
      const box = screen.getByTestId(`cs-row-query_normalizer-step-${step}-checkbox`);
      expect(box).toBeInTheDocument();
      expect(screen.getByText(glossary[NORMALIZER_STEP_GLOSSARY_KEYS[step]].short)).toBeVisible();
    }
  });

  it('(b) toggling lowercase then trim emits steps in STEP_ORDER', () => {
    const onChange = vi.fn();
    // First toggle from empty: pick lowercase.
    const { rerender } = wrap(
      <RowNormalizerPipeline paramName="query_normalizer" steps={[]} onChange={onChange} />,
    );
    fireEvent.click(screen.getByTestId('cs-row-query_normalizer-step-lowercase-checkbox'));
    expect(onChange).toHaveBeenLastCalledWith(['lowercase']);

    // Controlled re-render with the new value, then pick trim.
    rerender(
      <TooltipProvider delayDuration={0}>
        <RowNormalizerPipeline
          paramName="query_normalizer"
          steps={['lowercase']}
          onChange={onChange}
        />
      </TooltipProvider>,
    );
    fireEvent.click(screen.getByTestId('cs-row-query_normalizer-step-trim-checkbox'));
    // STEP_ORDER puts lowercase before trim regardless of click order.
    expect(onChange).toHaveBeenLastCalledWith(['lowercase', 'trim']);
  });

  it('(c) cardinality preview reads 4 for a two-step pipeline', () => {
    expect(
      estimateParamCardinality({ type: 'normalizer_pipeline', steps: ['lowercase', 'trim'] }),
    ).toBe(4);
    wrap(
      <RowCardinality
        paramName="query_normalizer"
        spec={{ type: 'normalizer_pipeline', steps: ['lowercase', 'trim'] }}
      />,
    );
    expect(screen.getByTestId('cs-row-query_normalizer-cardinality')).toHaveTextContent('4 states');
  });

  it('(d) empty-steps row is flagged incomplete; helper clears once a step is picked', () => {
    const { rerender } = wrap(
      <RowNormalizerPipeline paramName="query_normalizer" steps={[]} onChange={() => {}} />,
    );
    expect(screen.getByTestId('cs-row-error-query_normalizer-steps')).toBeInTheDocument();

    rerender(
      <TooltipProvider delayDuration={0}>
        <RowNormalizerPipeline
          paramName="query_normalizer"
          steps={['lowercase']}
          onChange={() => {}}
        />
      </TooltipProvider>,
    );
    expect(screen.queryByTestId('cs-row-error-query_normalizer-steps')).toBeNull();
  });

  it('toggling a selected step off removes it', () => {
    const onChange = vi.fn();
    wrap(
      <RowNormalizerPipeline
        paramName="query_normalizer"
        steps={['lowercase', 'trim']}
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByTestId('cs-row-query_normalizer-step-lowercase-checkbox'));
    expect(onChange).toHaveBeenLastCalledWith(['trim']);
  });
});
