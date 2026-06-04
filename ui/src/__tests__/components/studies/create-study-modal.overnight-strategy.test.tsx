// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * feat_overnight_final_solution Story 1.2 — wizard Strategy toggle.
 *
 * AC-4: toggle hidden when auto_followup_depth = 0/Off; visible with
 * `"narrow"` default when depth >= 1.
 * AC-5: submit with strategy="follow_suggestions" → POST body has both
 * config.auto_followup_depth and config.auto_followup_strategy.
 * Backward-compat: depth>=1 without explicit toggle change → wire value
 * `"narrow"` (so the validator's pair-rule is satisfied and the worker
 * dispatches the legacy path).
 *
 * Mirrors the test patterns in
 * create-study-modal.auto-followup.test.tsx (the existing depth selector
 * tests) — reuses the same shadcn-select mock + walkToStep5 helper shape.
 */

import { http, HttpResponse } from 'msw';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

import { TooltipProvider } from '@/components/ui/tooltip';

import { server } from '../../setup';

vi.mock('@/components/ui/select', async () => {
  const { mockShadcnSelect } = await import('../../helpers/shadcn-select-mock');
  return mockShadcnSelect();
});

vi.mock('sonner', () => ({
  toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() }),
  Toaster: () => null,
}));

const { CreateStudyModal } = await import('@/components/studies/create-study-modal');

const API_BASE = 'http://api.test';

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider delayDuration={0}>{node}</TooltipProvider>
    </QueryClientProvider>,
  );
}

interface PostBody {
  config?: {
    auto_followup_depth?: unknown;
    auto_followup_strategy?: unknown;
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

function mockBackend() {
  const postBodies: PostBody[] = [];
  server.use(
    http.get(`${API_BASE}/api/v1/clusters`, () =>
      HttpResponse.json(
        {
          data: [
            {
              id: 'c1',
              name: 'local-es',
              engine_type: 'elasticsearch',
              environment: 'dev',
              base_url: 'http://localhost:9200',
              auth_kind: 'es_apikey',
              created_at: '2026-05-12T00:00:00Z',
              health_check: {
                status: 'green',
                version: '9.4.0',
                checked_at: '2026-05-12T00:00:00Z',
                error: null,
              },
            },
          ],
          next_cursor: null,
          has_more: false,
        },
        { headers: { 'X-Total-Count': '1' } },
      ),
    ),
    http.get(`${API_BASE}/api/v1/clusters/c1/schema`, () => HttpResponse.json({ fields: [] })),
    http.get(`${API_BASE}/api/v1/clusters/c1/targets`, () =>
      HttpResponse.json({ data: [{ name: 'products', doc_count: 42 }] }),
    ),
    http.get(`${API_BASE}/api/v1/query-sets`, () =>
      HttpResponse.json(
        {
          data: [{ id: 'qs1', name: 'demo', query_count: 5, created_at: '2026-05-12T00:00:00Z' }],
          next_cursor: null,
          has_more: false,
        },
        { headers: { 'X-Total-Count': '1' } },
      ),
    ),
    http.get(`${API_BASE}/api/v1/judgment-lists`, () =>
      HttpResponse.json(
        {
          data: [
            {
              id: 'jl1',
              name: 'demo',
              status: 'complete',
              source: 'llm',
              created_at: '2026-05-12T00:00:00Z',
            },
          ],
          next_cursor: null,
          has_more: false,
        },
        { headers: { 'X-Total-Count': '1' } },
      ),
    ),
    http.get(`${API_BASE}/api/v1/query-templates`, () =>
      HttpResponse.json(
        {
          data: [
            {
              id: 'tpl1',
              name: 'T1',
              engine_type: 'elasticsearch',
              version: 1,
              created_at: '2026-05-12T00:00:00Z',
              declared_params: { boost_title: 'float' },
            },
          ],
          next_cursor: null,
          has_more: false,
        },
        { headers: { 'X-Total-Count': '1' } },
      ),
    ),
    http.get(`${API_BASE}/api/v1/query-templates/tpl1`, () =>
      HttpResponse.json({
        id: 'tpl1',
        name: 'T1',
        engine_type: 'elasticsearch',
        body: '{}',
        declared_params: { boost_title: 'float' },
        version: 1,
        parent_id: null,
        created_at: '2026-05-12T00:00:00Z',
      }),
    ),
    http.post(`${API_BASE}/api/v1/studies`, async ({ request }) => {
      const body = (await request.json()) as PostBody;
      postBodies.push(body);
      return HttpResponse.json({ id: 'st1', name: 'demo', status: 'queued' });
    }),
  );
  return { postBodies };
}

async function walkToStep5(): Promise<void> {
  await waitFor(() => expect(screen.getByRole('option', { name: /local-es/ })).toBeInTheDocument());
  fireEvent.change(screen.getByLabelText('Cluster'), { target: { value: 'c1' } });
  await waitFor(() =>
    expect(screen.queryAllByRole('option', { name: /products/ }).length).toBeGreaterThan(0),
  );
  fireEvent.change(screen.getByLabelText('Target index / collection'), {
    target: { value: 'products' },
  });
  fireEvent.click(screen.getByTestId('step-next'));
  await waitFor(() => expect(screen.getByTestId('step-2')).toBeInTheDocument());
  await waitFor(() =>
    expect(screen.queryAllByRole('option', { name: 'demo' }).length).toBeGreaterThan(0),
  );
  fireEvent.change(screen.getByLabelText('Query set'), { target: { value: 'qs1' } });
  await waitFor(() => {
    expect(screen.queryAllByRole('option', { name: 'demo' }).length).toBeGreaterThanOrEqual(2);
  });
  fireEvent.change(screen.getByLabelText('Judgment list'), { target: { value: 'jl1' } });
  fireEvent.click(screen.getByTestId('step-next'));
  await waitFor(() => expect(screen.getByTestId('step-3')).toBeInTheDocument());
  await waitFor(() => expect(screen.getAllByRole('option').length).toBeGreaterThan(0));
  fireEvent.change(screen.getByLabelText('Query template (filtered by engine)'), {
    target: { value: 'tpl1' },
  });
  fireEvent.click(screen.getByTestId('step-next'));
  await waitFor(() => expect(screen.getByTestId('step-4')).toBeInTheDocument());
  fireEvent.change(screen.getByLabelText('Study name'), {
    target: { value: 'overnight-strategy-test' },
  });
  fireEvent.click(screen.getByTestId('step-next'));
  await waitFor(() => expect(screen.getByTestId('step-5')).toBeInTheDocument());
}

function getDepthSelect(): HTMLSelectElement {
  return screen.getByTestId('cs-auto-followup') as HTMLSelectElement;
}

function queryStrategySelect(): HTMLSelectElement | null {
  return screen.queryByTestId('cs-overnight-strategy') as HTMLSelectElement | null;
}

describe('CreateStudyModal — overnight Strategy toggle (Story 1.2, FR-2)', () => {
  afterEach(() => server.resetHandlers());

  // AC-4 (hidden): depth=0 means the toggle is not in the DOM at all.
  it('AC-4: Strategy toggle is NOT rendered when auto_followup_depth = Off (0)', async () => {
    mockBackend();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToStep5();

    expect(getDepthSelect().value).toBe('0');
    expect(queryStrategySelect()).toBeNull();
  });

  // AC-4 (visible w/ default): depth becomes >= 1 → toggle appears with
  // "narrow" selected by default so the wire contract is the safe legacy
  // behavior unless the operator opts in.
  it('AC-4: Strategy toggle appears with "narrow" default when depth becomes >= 1', async () => {
    mockBackend();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToStep5();

    fireEvent.change(getDepthSelect(), { target: { value: '3' } });
    await waitFor(() => expect(getDepthSelect().value).toBe('3'));

    const strategy = queryStrategySelect();
    expect(strategy).not.toBeNull();
    expect(strategy!.value).toBe('narrow');
  });

  // AC-4 (hide on revert): depth back to Off hides the toggle in the
  // same render cycle.
  it('AC-4: Strategy toggle disappears when depth returns to Off', async () => {
    mockBackend();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToStep5();

    fireEvent.change(getDepthSelect(), { target: { value: '2' } });
    await waitFor(() => expect(queryStrategySelect()).not.toBeNull());

    fireEvent.change(getDepthSelect(), { target: { value: '0' } });
    await waitFor(() => expect(getDepthSelect().value).toBe('0'));
    expect(queryStrategySelect()).toBeNull();
  });

  // AC-5: explicit follow_suggestions opt-in → submit payload carries
  // both config keys.
  it('AC-5: submit with depth=3 + strategy=follow_suggestions → POST body has both keys', async () => {
    const { postBodies } = mockBackend();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToStep5();

    fireEvent.change(getDepthSelect(), { target: { value: '3' } });
    await waitFor(() => expect(queryStrategySelect()).not.toBeNull());
    fireEvent.change(queryStrategySelect()!, { target: { value: 'follow_suggestions' } });
    await waitFor(() => expect(queryStrategySelect()!.value).toBe('follow_suggestions'));

    fireEvent.click(screen.getByRole('button', { name: /Create study/i }));

    await waitFor(() => expect(postBodies.length).toBeGreaterThan(0));
    expect(postBodies[0]!.config?.auto_followup_depth).toBe(3);
    expect(postBodies[0]!.config?.auto_followup_strategy).toBe('follow_suggestions');
  });

  // Backward-compat default: depth>=1 with no toggle change → wire value
  // "narrow". The validator's pair-rule requires the strategy be set when
  // depth>=1; sending "narrow" preserves the legacy worker path while
  // satisfying the contract.
  it('submit with depth=2 (default strategy) → POST body has auto_followup_strategy="narrow"', async () => {
    const { postBodies } = mockBackend();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToStep5();

    fireEvent.change(getDepthSelect(), { target: { value: '2' } });
    await waitFor(() => expect(getDepthSelect().value).toBe('2'));

    fireEvent.click(screen.getByRole('button', { name: /Create study/i }));

    await waitFor(() => expect(postBodies.length).toBeGreaterThan(0));
    expect(postBodies[0]!.config?.auto_followup_depth).toBe(2);
    expect(postBodies[0]!.config?.auto_followup_strategy).toBe('narrow');
  });

  // depth=Off → omit both keys (legacy backward-compat, byte-identical
  // wire shape to pre-feature studies).
  it('submit with depth=Off → POST body omits both auto_followup_depth and auto_followup_strategy', async () => {
    const { postBodies } = mockBackend();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToStep5();

    expect(getDepthSelect().value).toBe('0');
    fireEvent.click(screen.getByRole('button', { name: /Create study/i }));

    await waitFor(() => expect(postBodies.length).toBeGreaterThan(0));
    const config = postBodies[0]!.config ?? {};
    expect('auto_followup_depth' in config).toBe(false);
    expect('auto_followup_strategy' in config).toBe(false);
  });
});
