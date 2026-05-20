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

function mockBackend(declared: Record<string, string>, templateName: string) {
  let studiesPostHit = 0;
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
              name: templateName,
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
    http.get(`${API_BASE}/api/v1/query-templates/tpl1`, () =>
      HttpResponse.json({
        id: 'tpl1',
        name: templateName,
        engine_type: 'elasticsearch',
        body: '{}',
        declared_params: declared,
        version: 1,
        parent_id: null,
        created_at: '2026-05-12T00:00:00Z',
      }),
    ),
    http.post(`${API_BASE}/api/v1/studies`, () => {
      studiesPostHit += 1;
      return HttpResponse.json({ id: 'st1', name: 'demo', status: 'queued' });
    }),
  );
  return { wasStudiesPostHit: () => studiesPostHit > 0 };
}

async function walkToStep4(): Promise<void> {
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
  await waitFor(() => expect(screen.getAllByRole('option').length).toBeGreaterThan(0));
  fireEvent.change(screen.getByLabelText('Query template (filtered by engine)'), {
    target: { value: 'tpl1' },
  });
  fireEvent.click(screen.getByTestId('step-next'));
  await waitFor(() => expect(screen.getByTestId('step-4')).toBeInTheDocument());
}

describe('CreateStudyModal — Step-4 client-side validation (FR-2 / FR-3 / AC-4)', () => {
  afterEach(() => server.resetHandlers());

  it('surfaces inline unknown-param error on Next-click without hitting POST /studies', async () => {
    const handlers = mockBackend({ boost_title: 'float' }, 'T1');
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToStep4();

    const textarea = (await screen.findByTestId('cs-search-space')) as HTMLTextAreaElement;
    await waitFor(() => expect(textarea.value).toContain('boost_title'));

    // Set study name to satisfy stepValid(3), then corrupt the auto-fill with a typo.
    fireEvent.change(screen.getByLabelText('Study name'), { target: { value: 'bad-run' } });
    fireEvent.change(textarea, {
      target: { value: '{"params": {"boost_titl": {"type": "float", "low": 0.5, "high": 10.0}}}' },
    });

    fireEvent.click(screen.getByTestId('step-next'));

    // Inline error renders, transition is blocked, no network call made.
    const err = await screen.findByTestId('cs-search-space-error');
    expect(err.textContent ?? '').toContain("Param 'boost_titl' is not declared");
    expect(err.textContent ?? '').toContain("template 'T1'");
    expect(screen.queryByTestId('step-5')).not.toBeInTheDocument();
    expect(handlers.wasStudiesPostHit()).toBe(false);
  });

  it('surfaces inline missing-declared-param error on Next-click', async () => {
    mockBackend({ boost_title: 'float', boost_body: 'float' }, 'T2');
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToStep4();

    const textarea = (await screen.findByTestId('cs-search-space')) as HTMLTextAreaElement;
    await waitFor(() => expect(textarea.value).toContain('boost_title'));

    fireEvent.change(screen.getByLabelText('Study name'), { target: { value: 'missing-run' } });
    fireEvent.change(textarea, {
      target: { value: '{"params": {"boost_title": {"type": "float", "low": 0.5, "high": 10.0}}}' },
    });

    fireEvent.click(screen.getByTestId('step-next'));

    const err = await screen.findByTestId('cs-search-space-error');
    expect(err.textContent ?? '').toContain("declares param 'boost_body'");
    expect(err.textContent ?? '').toContain('is missing from the search space');
    expect(screen.queryByTestId('step-5')).not.toBeInTheDocument();
  });

  it('renders the __placeholder__ warning when a categorical contains the sentinel', async () => {
    mockBackend({ some_string_param: 'string' }, 'T3');
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToStep4();

    const textarea = (await screen.findByTestId('cs-search-space')) as HTMLTextAreaElement;
    await waitFor(() => expect(textarea.value).toContain('__placeholder__'));

    await waitFor(() => expect(screen.getByTestId('cs-placeholder-warning')).toBeInTheDocument());
  });
});
