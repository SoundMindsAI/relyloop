/**
 * Story 4.1 — accessibility invariants for `<SearchSpaceBuilder>`.
 *
 * Asserts:
 *   1. Every <Input> has a <Label htmlFor> association (numeric inputs +
 *      categorical chip input).
 *   2. Row errors use role="alert" + aria-live="polite".
 *   3. "Add custom param" button is focusable (no native `disabled`) AND
 *      carries aria-disabled="true" per FR-10.
 *   4. The "Edit template" link inside the popover content is reachable
 *      (rendered in the DOM with the cs-row-add-custom-link test ID).
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';

import { TooltipProvider } from '@/components/ui/tooltip';
import type { QueryTemplateDetail } from '@/lib/api/query-templates';
import { SearchSpaceBuilder } from '@/components/studies/search-space-builder';

vi.mock('@/components/ui/select', async () => {
  const { mockShadcnSelect } = await import('../../helpers/shadcn-select-mock');
  return mockShadcnSelect();
});

function makeTemplate(declared_params: Record<string, string>): QueryTemplateDetail {
  return {
    id: 't1',
    name: 'test-template',
    engine_type: 'elasticsearch',
    body: '{}',
    declared_params,
    version: 1,
    parent_id: null,
    created_at: '2026-05-20T00:00:00Z',
  };
}

afterEach(() => cleanup());

describe('SearchSpaceBuilder a11y (Story 4.1)', () => {
  it('numeric inputs have <Label htmlFor> associations', () => {
    render(
      <TooltipProvider delayDuration={0}>
        <SearchSpaceBuilder
          value={'{"params":{"boost":{"type":"float","low":0.5,"high":10}}}'}
          onChange={vi.fn()}
          templateBody={makeTemplate({ boost: 'float' })}
          templateId="t1"
          templateFetchStatus="ok"
        />
      </TooltipProvider>,
    );

    const lowInput = screen.getByTestId('cs-row-boost-low') as HTMLInputElement;
    const highInput = screen.getByTestId('cs-row-boost-high') as HTMLInputElement;
    expect(lowInput.id).toBe('cs-row-boost-low');
    expect(highInput.id).toBe('cs-row-boost-high');

    // <Label htmlFor> exposes the association via the input's labels collection.
    expect(lowInput.labels?.length).toBeGreaterThan(0);
    expect(lowInput.labels![0]!.textContent).toMatch(/low/i);
    expect(highInput.labels?.length).toBeGreaterThan(0);
    expect(highInput.labels![0]!.textContent).toMatch(/high/i);
  });

  it('row error on inverted bounds uses role="alert" + aria-live="polite"', () => {
    render(
      <TooltipProvider delayDuration={0}>
        <SearchSpaceBuilder
          // low > high → row error fires.
          value={'{"params":{"boost":{"type":"float","low":10,"high":5}}}'}
          onChange={vi.fn()}
          templateBody={makeTemplate({ boost: 'float' })}
          templateId="t1"
          templateFetchStatus="ok"
        />
      </TooltipProvider>,
    );

    const err = screen.getByTestId('cs-row-error-boost');
    expect(err).toHaveAttribute('role', 'alert');
    expect(err).toHaveAttribute('aria-live', 'polite');
  });

  it('Add custom param button is focusable with aria-disabled (NOT native disabled)', () => {
    render(
      <TooltipProvider delayDuration={0}>
        <SearchSpaceBuilder
          value={'{"params":{"boost":{"type":"float","low":0.5,"high":10}}}'}
          onChange={vi.fn()}
          templateBody={makeTemplate({ boost: 'float' })}
          templateId="t1"
          templateFetchStatus="ok"
        />
      </TooltipProvider>,
    );

    const button = screen.getByTestId('cs-add-custom-param') as HTMLButtonElement;
    expect(button).not.toBeDisabled();
    expect(button).toHaveAttribute('aria-disabled', 'true');
    // Focusable: tabIndex defaults to 0 for native button without `disabled`.
    expect(button.tabIndex).toBeGreaterThanOrEqual(0);
  });

  it('Edit template link inside popover content carries the expected test ID + href', () => {
    render(
      <TooltipProvider delayDuration={0}>
        <SearchSpaceBuilder
          value={'{"params":{"boost":{"type":"float","low":0.5,"high":10}}}'}
          onChange={vi.fn()}
          templateBody={makeTemplate({ boost: 'float' })}
          templateId="t1"
          templateFetchStatus="ok"
        />
      </TooltipProvider>,
    );

    // Open the popover (controlled via onFocus / onMouseEnter on the trigger).
    const button = screen.getByTestId('cs-add-custom-param');
    fireEvent.focus(button);

    // The Popover renders content into a Radix portal — query via document.
    const link = document.querySelector(
      '[data-testid="cs-row-add-custom-link"]',
    ) as HTMLAnchorElement | null;
    expect(link).not.toBeNull();
    expect(link!.getAttribute('href')).toBe('/templates/t1');
  });
});
