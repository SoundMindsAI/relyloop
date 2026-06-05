// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { ParamDiffPanel } from '@/components/studies/comparison/param-diff-panel';

describe('ParamDiffPanel (FR-5 / AC-16)', () => {
  it('= for shared-equal, Δ for differing, em-dash + Δ for one-sided', () => {
    render(
      <ParamDiffPanel
        llmConfig={{ tie_breaker: 0.3, boost: 1.0, only_llm: 5 }}
        ubiConfig={{ tie_breaker: 0.3, boost: 2.0 }}
      />,
    );
    expect(screen.getByTestId('compare-param-row-tie_breaker')).toHaveTextContent('=');
    expect(screen.getByTestId('compare-param-row-boost')).toHaveTextContent('Δ');
    const onlyLlm = screen.getByTestId('compare-param-row-only_llm');
    expect(onlyLlm).toHaveTextContent('Δ');
    expect(onlyLlm).toHaveTextContent('—'); // missing UBI side
  });

  it('empty configs → no-params message', () => {
    render(<ParamDiffPanel llmConfig={null} ubiConfig={null} />);
    expect(screen.queryByTestId('compare-param-diff-table')).toBeNull();
    expect(screen.getByText(/No recommended parameters/i)).toBeInTheDocument();
  });
});
