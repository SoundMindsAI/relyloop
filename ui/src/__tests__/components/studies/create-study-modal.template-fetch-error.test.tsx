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

function mockListsCommon() {
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
              name: 'broken-template',
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

async function walkToStep3AndPickTemplate(): Promise<void> {
  await waitFor(() => expect(screen.getByRole('option', { name: /local-es/ })).toBeInTheDocument());
  fireEvent.change(screen.getByLabelText('Cluster'), { target: { value: 'c1' } });
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
    expect(screen.getByRole('option', { name: /broken-template/ })).toBeInTheDocument(),
  );
  fireEvent.change(screen.getByLabelText('Query template (filtered by engine)'), {
    target: { value: 'tpl1' },
  });
}

describe('CreateStudyModal — template fetch error paths (§11)', () => {
  afterEach(() => server.resetHandlers());

  it('renders the Retry control on a transient 5xx; Step-4 Next remains enabled', async () => {
    mockListsCommon();
    let attempt = 0;
    server.use(
      http.get(`${API_BASE}/api/v1/query-templates/tpl1`, () => {
        attempt += 1;
        if (attempt === 1) {
          // 500 with retryable=false — the apiClient's auto-retry policy
          // only fires for 503 + retryable=true. We want the error to
          // surface to the UI immediately so the user sees the Retry
          // button (versus apiClient retrying internally with backoff).
          return HttpResponse.json(
            { detail: { error_code: 'INTERNAL_ERROR', message: 'boom', retryable: false } },
            { status: 500 },
          );
        }
        return HttpResponse.json({
          id: 'tpl1',
          name: 'broken-template',
          engine_type: 'elasticsearch',
          body: '{}',
          declared_params: { boost_title: 'float' },
          version: 1,
          parent_id: null,
          created_at: '2026-05-12T00:00:00Z',
        });
      }),
    );

    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToStep3AndPickTemplate();

    fireEvent.click(screen.getByTestId('step-next'));
    await waitFor(() => expect(screen.getByTestId('step-4')).toBeInTheDocument());

    // Transient retry surface visible.
    await waitFor(() => expect(screen.getByTestId('cs-template-retry')).toBeInTheDocument());
    // Click Retry; the 2nd attempt resolves with a real body, retry surface goes away.
    fireEvent.click(screen.getByText('Retry'));
    await waitFor(() => expect(screen.queryByTestId('cs-template-retry')).toBeNull());

    // Auto-fill landed after retry.
    await waitFor(() =>
      expect((screen.getByTestId('cs-search-space') as HTMLTextAreaElement).value).toContain(
        'boost_title',
      ),
    );
  });

  it('bumps the user back to Step 3 when the template detail returns 404', async () => {
    mockListsCommon();
    server.use(
      http.get(`${API_BASE}/api/v1/query-templates/tpl1`, () =>
        HttpResponse.json(
          { detail: { error_code: 'TEMPLATE_NOT_FOUND', message: 'gone', retryable: false } },
          { status: 404 },
        ),
      ),
    );

    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToStep3AndPickTemplate();

    // The 404 effect fires while we're still on Step 3 — Next stays disabled
    // since template_id was cleared, and we never reach Step 4.
    await waitFor(() => {
      expect(screen.getByTestId('step-next')).toBeDisabled();
    });
    expect(screen.queryByTestId('step-4')).not.toBeInTheDocument();
  });
});
