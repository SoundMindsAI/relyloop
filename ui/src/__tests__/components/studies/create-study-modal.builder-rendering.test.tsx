/**
 * Story 1.2 — per-row builder rendering keyed off `declared_params`.
 *
 * Mounts `<SearchSpaceBuilder>` directly (no full-modal context needed
 * for these assertions; the modal integration is covered by the 7
 * existing `create-study-modal.*` tests). Tests:
 *
 *   AC-1: rows render in `Object.keys(declared_params)` order
 *   FR-1: row containers carry the `cs-param-row-{name}` test ID prefix
 *         (distinct from `cs-row-{name}-{control}` sub-control IDs)
 *   FR-1: name chip + simple-form badge appear in each row
 *   FR-1: rows render keyed off `declared_params`, NOT parsed JSON params
 *         (extra JSON keys don't render; missing JSON keys still render
 *         as empty/unset rows)
 *   FR-11: tooltip slots for `.param_spec` / `.log` / `.cardinality` are
 *          present (via the canonical `tooltip-trigger-{key}` test IDs
 *          emitted by `<InfoTooltip>`)
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';

import { TooltipProvider } from '@/components/ui/tooltip';
import type { QueryTemplateDetail } from '@/lib/api/query-templates';
import { SearchSpaceBuilder } from '@/components/studies/search-space-builder';

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

function mountBuilder(opts: {
  value?: string;
  declared_params?: Record<string, string>;
  templateBody?: QueryTemplateDetail | null;
  templateFetchStatus?: 'idle' | 'ok' | '404' | 'transient';
}): ReturnType<typeof render> {
  const value = opts.value ?? '{"params":{}}';
  const templateBody =
    opts.templateBody !== undefined ? opts.templateBody : makeTemplate(opts.declared_params ?? {});
  return render(
    <TooltipProvider delayDuration={0}>
      <SearchSpaceBuilder
        value={value}
        onChange={vi.fn()}
        templateBody={templateBody}
        templateId="t1"
        templateFetchStatus={opts.templateFetchStatus ?? 'ok'}
      />
    </TooltipProvider>,
  );
}

afterEach(() => cleanup());

describe('SearchSpaceBuilder per-row rendering (Story 1.2)', () => {
  it('AC-1: renders exactly one row per declared_params key, in iteration order', () => {
    mountBuilder({
      declared_params: { boost_title: 'float', min_should_match: 'int', operator: 'string' },
      value:
        '{"params":{"boost_title":{"type":"float","low":0.5,"high":10},"min_should_match":{"type":"int","low":0,"high":5},"operator":{"type":"categorical","choices":["__placeholder__"]}}}',
    });

    // Row containers use the `cs-param-row-{name}` prefix; sub-controls use
    // `cs-row-{name}-{control}`. The CSS-attribute selector `[data-testid^=...]`
    // anchored at `cs-param-row-` matches containers only.
    const containers = document.querySelectorAll('[data-testid^="cs-param-row-"]');
    // Each container has 2 child spans (name + simpleform) tagged with
    // `cs-param-row-{name}-{name|simpleform}` — they ALSO match the prefix.
    // Filter by checking that the test-id does NOT include a `-name` or
    // `-simpleform` suffix.
    const rowContainerIds = [...containers]
      .map((el) => el.getAttribute('data-testid')!)
      .filter((id) => !id.endsWith('-name') && !id.endsWith('-simpleform'));
    expect(rowContainerIds).toEqual([
      'cs-param-row-boost_title',
      'cs-param-row-min_should_match',
      'cs-param-row-operator',
    ]);
  });

  it('FR-1: row identity comes from declared_params, NOT parsed JSON params', () => {
    // declared_params has `boost`; JSON has an unrelated `unknown` key + no
    // `boost` spec → builder should render exactly ONE row for `boost`, in
    // empty/unset state. The `unknown` JSON key does NOT render as a row.
    mountBuilder({
      declared_params: { boost: 'float' },
      value: '{"params":{"unknown":{"type":"float","low":0,"high":1}}}',
    });

    expect(document.querySelector('[data-testid="cs-param-row-boost"]')).not.toBeNull();
    expect(document.querySelector('[data-testid="cs-param-row-unknown"]')).toBeNull();
    // The boost row is empty/unset because the JSON doesn't supply its spec.
    expect(screen.getByTestId('cs-row-boost-type-display').textContent).toBe('unset');
  });

  it('FR-1: name chip + simple-form badge render for each row', () => {
    mountBuilder({
      declared_params: { boost: 'float' },
      value: '{"params":{"boost":{"type":"float","low":0.5,"high":10}}}',
    });

    expect(screen.getByTestId('cs-param-row-boost-name').textContent).toBe('boost');
    expect(screen.getByTestId('cs-param-row-boost-simpleform').textContent).toBe('float');
  });

  it('FR-11: tooltip slots wired for .param_spec / .log / .cardinality', () => {
    mountBuilder({
      declared_params: { boost: 'float' },
      value: '{"params":{"boost":{"type":"float","low":0.5,"high":10}}}',
    });

    // <InfoTooltip> emits `tooltip-trigger-{glossaryKey}` test IDs.
    expect(screen.getByTestId('tooltip-trigger-study.search_space.param_spec')).toBeInTheDocument();
    expect(screen.getByTestId('tooltip-trigger-study.search_space.log')).toBeInTheDocument();
    expect(
      screen.getByTestId('tooltip-trigger-study.search_space.cardinality'),
    ).toBeInTheDocument();
  });
});
