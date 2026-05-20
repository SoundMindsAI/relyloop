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

describe('CreateStudyModal — zero-declared-params template blocks Step-3 → Step-4 (§11 edge)', () => {
  afterEach(() => server.resetHandlers());

  it('disables Next on Step 3 and surfaces inline error when declared_params is empty', async () => {
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
            data: [
              { id: 'qs1', name: 'demo', cluster_id: 'c1', created_at: '2026-05-12T00:00:00Z' },
            ],
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
                id: 'tpl-zero',
                name: 'empty-template',
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
      http.get(`${API_BASE}/api/v1/query-templates/tpl-zero`, () =>
        HttpResponse.json({
          id: 'tpl-zero',
          name: 'empty-template',
          engine_type: 'elasticsearch',
          body: '{}',
          declared_params: {},
          version: 1,
          parent_id: null,
          created_at: '2026-05-12T00:00:00Z',
        }),
      ),
    );

    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);

    // Walk to Step 3.
    await waitFor(() =>
      expect(screen.getByRole('option', { name: /local-es/ })).toBeInTheDocument(),
    );
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
    await waitFor(() =>
      expect(screen.getByRole('option', { name: /empty-template/ })).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByLabelText('Query template (filtered by engine)'), {
      target: { value: 'tpl-zero' },
    });

    // Once the template body returns with declared_params: {}, the inline
    // error must surface and Next must be disabled.
    await waitFor(() => expect(screen.getByTestId('cs-zero-declared-error')).toBeInTheDocument());
    expect(screen.getByTestId('step-next')).toBeDisabled();
  });
});
