/**
 * Story 3.1 — builder ↔ textarea responsive layout + cross-surface
 * round-trip behavior (FR-8 + AC-9 + AC-12).
 *
 * Mounts `<ResponsiveLayout>` directly with a `<SearchSpaceBuilder>` +
 * mock textarea pair so the layout invariants can be asserted without
 * mounting the full modal:
 *   (a) at desktop viewport, both slot test IDs resolve
 *   (b) tab toggle is hidden via `lg:hidden` class
 *   (c) clicking JSON tab adds `hidden` class to builder slot;
 *       textarea slot remains in the DOM
 *   (d) typing invalid JSON into the textarea switches the builder to
 *       the `cs-search-space-builder-parse-error` placeholder
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';

import { TooltipProvider } from '@/components/ui/tooltip';
import type { QueryTemplateDetail } from '@/lib/api/query-templates';
import { SearchSpaceBuilder } from '@/components/studies/search-space-builder';
import { ResponsiveLayout } from '@/components/studies/search-space-builder/responsive-layout';

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

function MountedLayout({ initialValue }: { initialValue: string }) {
  const [value, setValue] = React.useState(initialValue);
  return (
    <TooltipProvider delayDuration={0}>
      <ResponsiveLayout
        builder={
          <SearchSpaceBuilder
            value={value}
            onChange={setValue}
            templateBody={makeTemplate({ boost: 'float' })}
            templateId="t1"
            templateFetchStatus="ok"
          />
        }
        textarea={
          <textarea
            data-testid="cs-search-space"
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
        }
      />
    </TooltipProvider>
  );
}

// Needs React in scope.
import * as React from 'react';

describe('SearchSpaceBuilder responsive layout (Story 3.1)', () => {
  it('(a) at desktop viewport, both slot test IDs resolve', () => {
    render(
      <MountedLayout initialValue={'{"params":{"boost":{"type":"float","low":0.5,"high":10}}}'} />,
    );
    expect(screen.getByTestId('cs-search-space-builder')).toBeInTheDocument();
    expect(screen.getByTestId('cs-search-space')).toBeInTheDocument();
  });

  it('(b) tab toggle is present and uses lg:hidden so it only shows on narrow viewports', () => {
    render(
      <MountedLayout initialValue={'{"params":{"boost":{"type":"float","low":0.5,"high":10}}}'} />,
    );
    const tabToggle = screen.getByTestId('cs-builder-tab-toggle');
    expect(tabToggle).toBeInTheDocument();
    expect(tabToggle.className).toContain('lg:hidden');
  });

  it('(c) clicking JSON tab applies hidden to builder slot; textarea still in DOM', () => {
    render(
      <MountedLayout initialValue={'{"params":{"boost":{"type":"float","low":0.5,"high":10}}}'} />,
    );
    fireEvent.click(screen.getByTestId('cs-builder-tab-json'));

    const builderSlot = screen.getByTestId('cs-builder-slot-builder');
    expect(builderSlot.className).toContain('hidden');
    // Textarea remains queryable via getByTestId (DOM presence, not visibility):
    expect(screen.getByTestId('cs-search-space')).toBeInTheDocument();
  });

  it('(d) typing invalid JSON in the textarea switches builder to parse-error placeholder', () => {
    render(
      <MountedLayout initialValue={'{"params":{"boost":{"type":"float","low":0.5,"high":10}}}'} />,
    );
    const textarea = screen.getByTestId('cs-search-space') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: '{not valid' } });

    expect(screen.getByTestId('cs-search-space-builder-parse-error')).toBeInTheDocument();
    // The builder's row containers no longer render.
    expect(document.querySelector('[data-testid="cs-param-row-boost"]')).toBeNull();
  });
});
