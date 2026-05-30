// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type ReactNode } from 'react';

import { TooltipProvider } from '@/components/ui/tooltip';

import { server } from '../../setup';

// Radix Select crashes inside jsdom's portal handling for this many-Select
// modal — replace it with a native `<select>` shim from the shared helper.
// The CreateStudyRequest contract (the thing this test verifies) is
// unchanged. The helper's shim is a superset (data-testid forwarding +
// disabled handling) of what this file originally inlined; the extra
// capabilities don't affect this test's assertions.
vi.mock('@/components/ui/select', async () => {
  const { mockShadcnSelect } = await import('../../helpers/shadcn-select-mock');
  return mockShadcnSelect();
});

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

function mockBackend() {
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
      HttpResponse.json({
        data: [
          { name: 'products', doc_count: 42 },
          { name: 'orders', doc_count: 12 },
        ],
      }),
    ),
    http.get(`${API_BASE}/api/v1/query-sets`, () =>
      HttpResponse.json(
        {
          data: [{ id: 'qs1', name: 'demo', cluster_id: 'c1', created_at: '2026-05-12T00:00:00Z' }],
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
              description: null,
              query_set_id: 'qs1',
              cluster_id: 'c1',
              status: 'complete',
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
              name: 'match-all',
              engine_type: 'elasticsearch',
              version: 1,
              created_at: '2026-05-12T00:00:00Z',
            },
          ],
          next_cursor: null,
          has_more: false,
        },
        { headers: { 'X-Total-Count': '1' } },
      ),
    ),
  );
}

describe('CreateStudyModal', () => {
  it('walks all 5 steps and POSTs the correct CreateStudyRequest shape', async () => {
    mockBackend();
    let captured: unknown = null;
    server.use(
      http.post(`${API_BASE}/api/v1/studies`, async ({ request }) => {
        captured = await request.json();
        return HttpResponse.json({ id: 'st1', name: 'demo', status: 'queued' });
      }),
    );

    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);

    // Step 1 — pick cluster + target
    await waitFor(() =>
      expect(screen.getByRole('option', { name: /local-es/ })).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByLabelText('Cluster'), { target: { value: 'c1' } });
    // After cluster pick, the target dropdown loads via /clusters/c1/targets.
    // Wait for the 'products' option to render before selecting it.
    await waitFor(() =>
      expect(screen.queryAllByRole('option', { name: /products/ }).length).toBeGreaterThan(0),
    );
    fireEvent.change(screen.getByLabelText('Target index / collection'), {
      target: { value: 'products' },
    });
    fireEvent.click(screen.getByTestId('step-next'));

    // Step 2 — query set + judgment list
    await waitFor(() => expect(screen.getByTestId('step-2')).toBeInTheDocument());
    await waitFor(() =>
      expect(screen.queryAllByRole('option', { name: 'demo' }).length).toBeGreaterThan(0),
    );
    fireEvent.change(screen.getByLabelText('Query set'), { target: { value: 'qs1' } });
    // Wait for the judgment-list options to populate (depends on query_set_id).
    await waitFor(() => {
      const opts = screen.queryAllByRole('option', { name: 'demo' });
      // Both query-set 'demo' and judgment-list 'demo' should be options now.
      expect(opts.length).toBeGreaterThanOrEqual(2);
    });
    fireEvent.change(screen.getByLabelText('Judgment list'), { target: { value: 'jl1' } });
    fireEvent.click(screen.getByTestId('step-next'));

    // Step 3 — template
    await waitFor(() => expect(screen.getByTestId('step-3')).toBeInTheDocument());
    await waitFor(() =>
      expect(screen.getByRole('option', { name: /match-all/ })).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByLabelText('Query template (filtered by engine)'), {
      target: { value: 'tpl1' },
    });
    fireEvent.click(screen.getByTestId('step-next'));

    // Step 4 — name + search space
    await waitFor(() => expect(screen.getByTestId('step-4')).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText('Study name'), { target: { value: 'first-run' } });
    fireEvent.change(screen.getByTestId('cs-search-space'), {
      target: { value: '{"boost": {"type": "float", "low": 0.1, "high": 2.0}}' },
    });
    fireEvent.click(screen.getByTestId('step-next'));

    // Step 5 — objective + stop condition + submit
    await waitFor(() => expect(screen.getByTestId('step-5')).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText('Max trials'), { target: { value: '25' } });
    fireEvent.click(screen.getByTestId('create-study-submit'));

    await waitFor(() => expect(captured).not.toBeNull());
    expect(captured).toMatchObject({
      name: 'first-run',
      cluster_id: 'c1',
      target: 'products',
      template_id: 'tpl1',
      query_set_id: 'qs1',
      judgment_list_id: 'jl1',
      search_space: { boost: { type: 'float', low: 0.1, high: 2.0 } },
      objective: { metric: 'ndcg', k: 10, direction: 'maximize' },
      config: {
        max_trials: 25,
        parallelism: 4,
        sampler: 'tpe',
        pruner: 'median',
      },
    });
  });
});

// ----------------------------------------------------------------------------
// feat_create_study_target_autocomplete Story F2 — target picker UX tests
// ----------------------------------------------------------------------------

describe('CreateStudyModal — Step 1 target picker (F2)', () => {
  it('renders a disabled "Pick a cluster first" placeholder and fires no targets GET before a cluster is picked', async () => {
    mockBackend();
    let targetsCalls = 0;
    server.use(
      http.get(`${API_BASE}/api/v1/clusters/c1/targets`, () => {
        targetsCalls += 1;
        return HttpResponse.json({ data: [{ name: 'products', doc_count: 42 }] });
      }),
    );

    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);

    // Wait for cluster dropdown to be ready (proxy for "modal mounted").
    await waitFor(() =>
      expect(screen.getByRole('option', { name: /local-es/ })).toBeInTheDocument(),
    );

    // Before any cluster is picked, the target trigger is disabled and no GET fired.
    const targetField = screen.getByLabelText('Target index / collection');
    expect(targetField).toBeDisabled();
    // Give the network a moment to NOT fire.
    await new Promise((r) => setTimeout(r, 20));
    expect(targetsCalls).toBe(0);
  });

  it('renders targets alphabetically sorted (FR-7) once a cluster is picked', async () => {
    mockBackend();
    server.use(
      http.get(`${API_BASE}/api/v1/clusters/c1/targets`, () =>
        HttpResponse.json({
          // Engine returns creation order; the frontend sorts alphabetically.
          data: [
            { name: 'reviews', doc_count: 1 },
            { name: 'orders', doc_count: 2 },
            { name: 'products', doc_count: 3 },
          ],
        }),
      ),
    );

    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);

    await waitFor(() =>
      expect(screen.getByRole('option', { name: /local-es/ })).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByLabelText('Cluster'), { target: { value: 'c1' } });

    // Wait for all three target options to render.
    await waitFor(() => {
      expect(screen.queryAllByRole('option', { name: /products/ }).length).toBeGreaterThan(0);
      expect(screen.queryAllByRole('option', { name: /orders/ }).length).toBeGreaterThan(0);
      expect(screen.queryAllByRole('option', { name: /reviews/ }).length).toBeGreaterThan(0);
    });

    // Find the target select element and read its options in DOM order.
    const targetField = screen.getByLabelText('Target index / collection') as HTMLSelectElement;
    const optionNames = Array.from(targetField.options)
      .map((o) => o.textContent ?? o.value)
      .filter((s) => s && !s.startsWith('Choose'));
    // Alphabetical order: orders, products, reviews.
    expect(optionNames.slice(0, 3)).toEqual([
      expect.stringContaining('orders'),
      expect.stringContaining('products'),
      expect.stringContaining('reviews'),
    ]);
  });

  it('toggles between dropdown and manual mode via the "Enter manually" button (AC-9)', async () => {
    mockBackend();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);

    await waitFor(() =>
      expect(screen.getByRole('option', { name: /local-es/ })).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByLabelText('Cluster'), { target: { value: 'c1' } });

    // Default: dropdown mode → toggle reads "Enter manually".
    const toggle = await screen.findByRole('button', { name: 'Enter manually' });
    fireEvent.click(toggle);

    // After click: input rendered, toggle label flips.
    const targetField = await screen.findByLabelText('Target index / collection');
    expect(targetField.tagName.toLowerCase()).toBe('input');
    expect(screen.getByRole('button', { name: 'Use dropdown' })).toBeInTheDocument();
  });

  it('auto-engages manual mode + shows amber hint on TARGETS_FORBIDDEN, no toast (AC-10 + AC-13 modal-level)', async () => {
    mockBackend();
    // Override the targets endpoint to return 403 TARGETS_FORBIDDEN.
    server.use(
      http.get(`${API_BASE}/api/v1/clusters/c1/targets`, () =>
        HttpResponse.json(
          {
            detail: {
              error_code: 'TARGETS_FORBIDDEN',
              message: 'cluster denied listing call',
              retryable: false,
            },
          },
          { status: 403 },
        ),
      ),
    );

    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);

    await waitFor(() =>
      expect(screen.getByRole('option', { name: /local-es/ })).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByLabelText('Cluster'), { target: { value: 'c1' } });

    // After the 403 lands, the modal auto-flips into manual mode and renders
    // the amber inline hint.
    await waitFor(() =>
      expect(screen.getByText(/Cluster restricts index listing/)).toBeInTheDocument(),
    );
    const targetField = screen.getByLabelText('Target index / collection');
    expect(targetField.tagName.toLowerCase()).toBe('input');
    // Toggle now reads "Use dropdown".
    expect(screen.getByRole('button', { name: 'Use dropdown' })).toBeInTheDocument();
  });

  it('cluster change resets target + manual-mode + clears amber hint (AC-8)', async () => {
    mockBackend();
    // Add a second cluster that DOES permit listing.
    server.use(
      http.get(`${API_BASE}/api/v1/clusters`, () =>
        HttpResponse.json(
          {
            data: [
              {
                id: 'c1',
                name: 'restricted',
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
              {
                id: 'c2',
                name: 'open',
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
          { headers: { 'X-Total-Count': '2' } },
        ),
      ),
      http.get(`${API_BASE}/api/v1/clusters/c1/targets`, () =>
        HttpResponse.json(
          {
            detail: {
              error_code: 'TARGETS_FORBIDDEN',
              message: 'cluster denied listing call',
              retryable: false,
            },
          },
          { status: 403 },
        ),
      ),
      http.get(`${API_BASE}/api/v1/clusters/c2/targets`, () =>
        HttpResponse.json({ data: [{ name: 'products', doc_count: 42 }] }),
      ),
    );

    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);

    await waitFor(() =>
      expect(screen.getByRole('option', { name: /restricted/ })).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByLabelText('Cluster'), { target: { value: 'c1' } });

    // c1 → TARGETS_FORBIDDEN auto-engages manual mode + amber hint.
    await waitFor(() =>
      expect(screen.getByText(/Cluster restricts index listing/)).toBeInTheDocument(),
    );

    // Switch to c2 (open cluster) → manualMode resets, hint disappears,
    // dropdown re-engages.
    fireEvent.change(screen.getByLabelText('Cluster'), { target: { value: 'c2' } });

    await waitFor(() =>
      expect(screen.queryByText(/Cluster restricts index listing/)).not.toBeInTheDocument(),
    );
    // Toggle is back to "Enter manually" (dropdown mode).
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Enter manually' })).toBeInTheDocument(),
    );
  });
});
