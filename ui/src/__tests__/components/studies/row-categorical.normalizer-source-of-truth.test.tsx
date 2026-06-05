// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * feat_query_normalization_tuning FR-7 / AC-11 — the reserved query_normalizer
 * row renders a constrained <Select> (sourced from NORMALIZER_VALUES via the
 * operator-declared subset), while every other Categorical param keeps the
 * free-form chip input.
 *
 * Radix <Select> is replaced with the shared native-<select> mock so jsdom can
 * drive the change event.
 */

import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

vi.mock('@/components/ui/select', async () => {
  const { mockShadcnSelect } = await import('../../helpers/shadcn-select-mock');
  return mockShadcnSelect();
});

import { RowCategorical } from '@/components/studies/search-space-builder/row-categorical';
import { TooltipProvider } from '@/components/ui/tooltip';
import { glossary } from '@/lib/glossary';

function wrap(node: React.ReactNode) {
  return render(<TooltipProvider delayDuration={0}>{node}</TooltipProvider>);
}

describe('RowCategorical — reserved query_normalizer row (FR-7 / AC-11)', () => {
  it('AC-11a: a non-reserved Categorical keeps the chip input', () => {
    wrap(<RowCategorical paramName="operator" choices={['AND', 'OR']} onChange={() => {}} />);
    expect(screen.getByTestId('cs-row-operator-choices-input')).toBeInTheDocument();
    expect(screen.queryByTestId('cs-row-operator-select')).toBeNull();
  });

  it('AC-11b: query_normalizer renders a Select with exactly the declared subset + glossary labels', () => {
    wrap(
      <RowCategorical
        paramName="query_normalizer"
        choices={['none', 'lowercase+trim']}
        onChange={() => {}}
      />,
    );
    expect(screen.getByTestId('cs-row-query_normalizer-select')).toBeInTheDocument();
    // Native-select mock prepends one empty option; the real choices are the
    // two non-empty options carrying the declared values.
    const options = screen.getAllByRole('option') as HTMLOptionElement[];
    const choiceOptions = options.filter((o) => o.value !== '');
    expect(choiceOptions.map((o) => o.value)).toEqual(['none', 'lowercase+trim']);
    // Labels are glossary-sourced (not raw wire values).
    expect(choiceOptions[0]!.textContent).toBe(
      glossary['search_space.query_normalizer.choice.none'].short,
    );
    expect(choiceOptions[1]!.textContent).toBe(
      glossary['search_space.query_normalizer.choice.lowercase_trim'].short,
    );
  });

  it('AC-11c: picking an option submits the single-value subset, not the universe', () => {
    const onChange = vi.fn();
    wrap(
      <RowCategorical
        paramName="query_normalizer"
        choices={['none', 'lowercase+trim']}
        onChange={onChange}
      />,
    );
    fireEvent.change(screen.getByTestId('cs-row-query_normalizer-select'), {
      target: { value: 'lowercase+trim' },
    });
    expect(onChange).toHaveBeenCalledWith(['lowercase+trim']);
  });

  describe('AC-11d: defense-in-depth — stray choices are filtered + warned', () => {
    let warnSpy: ReturnType<typeof vi.spyOn>;
    beforeEach(() => {
      warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    });
    afterEach(() => {
      warnSpy.mockRestore();
    });

    it('renders only the in-allowlist option and warns on the stray', () => {
      wrap(
        <RowCategorical
          paramName="query_normalizer"
          choices={['none', 'stem']}
          onChange={() => {}}
        />,
      );
      const choiceOptions = (screen.getAllByRole('option') as HTMLOptionElement[]).filter(
        (o) => o.value !== '',
      );
      expect(choiceOptions.map((o) => o.value)).toEqual(['none']);
      expect(warnSpy).toHaveBeenCalled();
    });
  });
});
