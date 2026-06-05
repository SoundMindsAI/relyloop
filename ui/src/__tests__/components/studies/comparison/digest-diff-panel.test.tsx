// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { DigestDiffPanel } from '@/components/studies/comparison/digest-diff-panel';

describe('DigestDiffPanel (FR-4)', () => {
  it('AC-11: differing narratives render a change-count summary', () => {
    render(
      <DigestDiffPanel
        llmNarrative="The loop converged on k1."
        ubiNarrative="The loop converged on title boost."
      />,
    );
    expect(screen.getByTestId('compare-digest-change-counts')).toBeInTheDocument();
    expect(screen.getByTestId('compare-digest-diff')).toBeInTheDocument();
  });

  it('missing one digest → placeholder on that side, other side renders', () => {
    render(<DigestDiffPanel llmNarrative={null} ubiNarrative="UBI narrative here." />);
    expect(screen.getByTestId('compare-digest-llm')).toHaveTextContent(
      'digest not available for this study',
    );
    expect(screen.getByTestId('compare-digest-ubi')).toHaveTextContent('UBI narrative here.');
    // No diff column when a side is missing.
    expect(screen.queryByTestId('compare-digest-diff')).toBeNull();
  });
});
