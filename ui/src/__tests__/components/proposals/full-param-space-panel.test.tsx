// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import '@testing-library/jest-dom/vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactElement } from 'react';
import { describe, expect, it } from 'vitest';

import { FullParamSpacePanel } from '@/components/proposals/full-param-space-panel';
import { TooltipProvider } from '@/components/ui/tooltip';

function renderWithProvider(ui: ReactElement) {
  return render(<TooltipProvider delayDuration={0}>{ui}</TooltipProvider>);
}

describe('FullParamSpacePanel', () => {
  it('Test 1 (AC-1): renders three groups with correct counts + alphabetical row order', () => {
    renderWithProvider(
      <FullParamSpacePanel
        configDiff={{
          title_boost: { from: 1.0, to: 2.5 },
          description_boost: { from: 1.0, to: 0.5 },
        }}
        searchSpaceParams={{ title_boost: {}, description_boost: {}, fuzziness: {} }}
        declaredParams={{
          title_boost: 'float',
          description_boost: 'float',
          fuzziness: 'int',
          function_score_decay: 'categorical',
        }}
      />,
    );
    expect(screen.getByTestId('param-space-group-tuned_changed')).toBeInTheDocument();
    expect(screen.getByTestId('param-space-row-tuned_changed-title_boost')).toBeInTheDocument();
    expect(
      screen.getByTestId('param-space-row-tuned_changed-description_boost'),
    ).toBeInTheDocument();
    expect(screen.getByTestId('param-space-group-tuned_unchanged')).toBeInTheDocument();
    expect(screen.getByTestId('param-space-row-tuned_unchanged-fuzziness')).toBeInTheDocument();
    expect(screen.getByTestId('param-space-group-untuned')).toBeInTheDocument();
    expect(screen.getByTestId('param-space-row-untuned-function_score_decay')).toBeInTheDocument();

    // Alphabetical within the tunedChanged group: description_boost before title_boost.
    const tunedChangedRows = screen
      .getAllByTestId(/^param-space-row-tuned_changed-/)
      .map((el) => el.getAttribute('data-testid'));
    expect(tunedChangedRows).toEqual([
      'param-space-row-tuned_changed-description_boost',
      'param-space-row-tuned_changed-title_boost',
    ]);
  });

  it('Test 2 (AC-2): renders legacy 2-tuple config_diff correctly (from/to normalized)', () => {
    renderWithProvider(
      <FullParamSpacePanel
        configDiff={{ boost: [1, 1.5] }}
        searchSpaceParams={undefined}
        declaredParams={{ boost: 'float' }}
      />,
    );
    const row = screen.getByTestId('param-space-row-tuned_changed-boost');
    expect(row).toHaveTextContent('boost');
    expect(row).toHaveTextContent('1'); // from
    expect(row).toHaveTextContent('1.5'); // to
  });

  it('Test 3 (AC-5): empty config_diff hides tunedChanged group; shows alphabetical tunedUnchanged', () => {
    renderWithProvider(
      <FullParamSpacePanel
        configDiff={{}}
        searchSpaceParams={{ foo: {}, bar: {} }}
        declaredParams={{ foo: 'float', bar: 'int', baz: 'categorical' }}
      />,
    );
    expect(screen.queryByTestId('param-space-group-tuned_changed')).toBeNull();
    expect(screen.getByTestId('param-space-row-tuned_unchanged-foo')).toBeInTheDocument();
    expect(screen.getByTestId('param-space-row-tuned_unchanged-bar')).toBeInTheDocument();
    expect(screen.getByTestId('param-space-row-untuned-baz')).toBeInTheDocument();
    // Alphabetical: bar before foo.
    const unchangedRows = screen
      .getAllByTestId(/^param-space-row-tuned_unchanged-/)
      .map((el) => el.getAttribute('data-testid'));
    expect(unchangedRows).toEqual([
      'param-space-row-tuned_unchanged-bar',
      'param-space-row-tuned_unchanged-foo',
    ]);
  });

  it('Test 4 (AC-6): config_diff drift key renders under tunedChanged with type "(unknown)"; no empty state', () => {
    renderWithProvider(
      <FullParamSpacePanel
        configDiff={{ removed_param: { from: 1, to: 2 } }}
        searchSpaceParams={undefined}
        declaredParams={{}}
      />,
    );
    const row = screen.getByTestId('param-space-row-tuned_changed-removed_param');
    expect(row).toHaveTextContent('removed_param');
    expect(row).toHaveTextContent('(unknown)');
    // Empty declaredParams does NOT trigger the empty state when config_diff has keys.
    expect(screen.queryByTestId('param-space-empty')).toBeNull();
  });

  it('Test 5 (AC-7): three rendering states are visually distinguishable', () => {
    renderWithProvider(
      <FullParamSpacePanel
        configDiff={{ title_boost: { from: 1.0, to: 2.5 } }}
        searchSpaceParams={{ title_boost: {}, fuzziness: {} }}
        declaredParams={{
          title_boost: 'float',
          fuzziness: 'int',
          function_score_decay: 'categorical',
        }}
      />,
    );
    // tunedChanged: has the from→to value treatment (an arrow glyph).
    const changedRow = screen.getByTestId('param-space-row-tuned_changed-title_boost');
    expect(changedRow).toHaveTextContent('→');
    // tunedUnchanged: carries the "(no change)" annotation.
    const unchangedRow = screen.getByTestId('param-space-row-tuned_unchanged-fuzziness');
    expect(unchangedRow).toHaveTextContent('(no change)');
    // untuned: carries the italic class.
    const untunedRow = screen.getByTestId('param-space-row-untuned-function_score_decay');
    expect(untunedRow).toHaveClass('italic');
  });

  it('Test 6 (AC-8): tooltip resolves via real hover interaction', async () => {
    const user = userEvent.setup();
    renderWithProvider(
      <FullParamSpacePanel
        configDiff={{ boost: { from: 1, to: 2 } }}
        searchSpaceParams={undefined}
        declaredParams={{ boost: 'float' }}
      />,
    );
    const trigger = screen.getByTestId('tooltip-trigger-proposal.full_param_space');
    expect(trigger).toBeInTheDocument();
    await user.hover(trigger);
    const body = await screen.findByTestId('tooltip-body-proposal.full_param_space');
    expect(body).toHaveTextContent(
      'Every parameter the template declares — grouped by whether the study tuned it and whether tuning changed the value.',
    );
  });

  it('Test 7 (defensive): both declaredParams and config_diff empty renders the empty state', () => {
    renderWithProvider(
      <FullParamSpacePanel configDiff={{}} searchSpaceParams={undefined} declaredParams={{}} />,
    );
    expect(screen.getByTestId('param-space-empty')).toBeInTheDocument();
    expect(screen.queryByTestId('param-space-group-tuned_changed')).toBeNull();
    expect(screen.queryByTestId('param-space-group-tuned_unchanged')).toBeNull();
    expect(screen.queryByTestId('param-space-group-untuned')).toBeNull();
  });
});
