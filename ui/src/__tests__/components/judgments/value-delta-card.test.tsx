// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Tests for `<ValueDeltaCard>` (feat_ubi_judgments Story 4.3 / FR-8 Capability D).
 */
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import { ValueDeltaCard } from '@/components/judgments/value-delta-card';

describe('<ValueDeltaCard>', () => {
  it('renders the coverage-only variant when no prior LLM list exists', () => {
    render(<ValueDeltaCard coveragePct={0.62} judgmentCount={234} />);
    expect(screen.getByText('What real signals bought you')).toBeInTheDocument();
    expect(screen.getByText('62%')).toBeInTheDocument();
    expect(screen.getByText('234')).toBeInTheDocument();
    expect(screen.queryByTestId('value-delta-prior-link')).not.toBeInTheDocument();
  });

  it('renders the delta variant with a link to the prior LLM list', () => {
    render(
      <ValueDeltaCard
        coveragePct={0.78}
        judgmentCount={500}
        priorList={{ id: 'prior-1', name: 'llm-baseline', judgment_count: 320 }}
      />,
    );
    const link = screen.getByTestId('value-delta-prior-link');
    expect(link).toHaveTextContent('llm-baseline');
    expect(link).toHaveAttribute('href', '/judgments/prior-1');
    expect(screen.getByText('320')).toBeInTheDocument();
  });

  it('falls back to "most" when coveragePct is null', () => {
    render(<ValueDeltaCard coveragePct={null} judgmentCount={42} />);
    expect(screen.getByText('most')).toBeInTheDocument();
  });

  // feat_ubi_llm_study_comparison FR-9 / AC-17 — the compare affordance.
  it('renders the "View matched study comparison" link when compareHref is set', () => {
    render(
      <ValueDeltaCard
        coveragePct={0.5}
        judgmentCount={10}
        compareHref="/studies/compare?a=llm-1&b=ubi-2"
      />,
    );
    const link = screen.getByTestId('value-delta-compare-link');
    expect(link).toHaveAttribute('href', '/studies/compare?a=llm-1&b=ubi-2');
  });

  it('omits the compare affordance when compareHref is null/absent', () => {
    render(<ValueDeltaCard coveragePct={0.5} judgmentCount={10} compareHref={null} />);
    expect(screen.queryByTestId('value-delta-compare-link')).toBeNull();
  });
});
