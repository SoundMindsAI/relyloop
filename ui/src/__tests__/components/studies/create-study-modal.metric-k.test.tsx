import { http, HttpResponse } from 'msw';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

import { TooltipProvider } from '@/components/ui/tooltip';
import { kTier } from '@/components/studies/create-study-modal';

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

function mockHappyPath() {
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
              name: 'T1',
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
        name: 'T1',
        engine_type: 'elasticsearch',
        body: '{}',
        declared_params: { boost_title: 'float' },
        version: 1,
        parent_id: null,
        created_at: '2026-05-12T00:00:00Z',
      }),
    ),
  );
}

async function walkToStep5(): Promise<void> {
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
  await waitFor(() => expect(screen.getByRole('option', { name: /T1/ })).toBeInTheDocument());
  fireEvent.change(screen.getByLabelText('Query template (filtered by engine)'), {
    target: { value: 'tpl1' },
  });
  fireEvent.click(screen.getByTestId('step-next'));
  await waitFor(() => expect(screen.getByTestId('step-4')).toBeInTheDocument());
  // Wait for auto-fill so step-4 Next can advance to step-5.
  await waitFor(() =>
    expect((screen.getByTestId('cs-search-space') as HTMLTextAreaElement).value).toContain(
      'boost_title',
    ),
  );
  fireEvent.change(screen.getByLabelText('Study name'), { target: { value: 'mk-run' } });
  fireEvent.click(screen.getByTestId('step-next'));
  await waitFor(() => expect(screen.getByTestId('step-5')).toBeInTheDocument());
}

describe('kTier helper', () => {
  it('classifies ndcg as required, map as optional, mrr as ignored', () => {
    expect(kTier('ndcg')).toBe('required');
    expect(kTier('map')).toBe('optional');
    expect(kTier('precision')).toBe('required');
    expect(kTier('recall')).toBe('required');
    expect(kTier('mrr')).toBe('ignored');
    expect(kTier('err')).toBe('ignored');
  });
});

describe('CreateStudyModal — Step-5 metric+k tri-state (FR-4)', () => {
  afterEach(() => server.resetHandlers());

  it('renders required-tier k Select + sub-label when metric is ndcg', async () => {
    mockHappyPath();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToStep5();

    // Default metric is ndcg; sub-label should announce "required for NDCG".
    expect(screen.getByTestId('cs-k-sublabel')).toHaveTextContent(
      'Top-k cutoff (required for NDCG)',
    );
    expect(screen.queryByTestId('cs-k-ignored-caption')).not.toBeInTheDocument();
    // Required tier does not render the "—" clearable option.
    expect(screen.queryByRole('option', { name: /full recall/ })).not.toBeInTheDocument();
  });

  it('renders optional-tier sub-label + clearable "—" entry when metric is map', async () => {
    mockHappyPath();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToStep5();

    fireEvent.change(screen.getByLabelText('Metric'), { target: { value: 'map' } });
    await waitFor(() =>
      expect(screen.getByTestId('cs-k-sublabel')).toHaveTextContent(
        'Top-k cutoff (optional — leave empty for full-recall MAP)',
      ),
    );
    expect(screen.getByRole('option', { name: /full recall/ })).toBeInTheDocument();
  });

  it('hides the k Select and renders the ignored-tier caption when metric is mrr', async () => {
    mockHappyPath();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToStep5();

    fireEvent.change(screen.getByLabelText('Metric'), { target: { value: 'mrr' } });
    await waitFor(() =>
      expect(screen.getByTestId('cs-k-ignored-caption')).toHaveTextContent(
        'MRR evaluates the full ranked list — no cutoff used.',
      ),
    );
    expect(screen.queryByTestId('cs-k-sublabel')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('k')).not.toBeInTheDocument();
  });

  it('preserves k when switching from a required-tier to optional-tier metric', async () => {
    mockHappyPath();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToStep5();

    // Default metric is ndcg, default k is 10. Switch to map.
    fireEvent.change(screen.getByLabelText('Metric'), { target: { value: 'map' } });
    await waitFor(() => expect(screen.getByTestId('cs-k-sublabel')).toHaveTextContent('optional'));
    // k still resolves to '10' on the native-select mock.
    const kSelect = screen.getByLabelText('k') as HTMLSelectElement;
    expect(kSelect.value).toBe('10');
  });

  it('clears k when switching from a required-tier to ignored-tier metric', async () => {
    mockHappyPath();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToStep5();

    // Default metric is ndcg with k=10. Switch to mrr → k cleared, Select gone.
    fireEvent.change(screen.getByLabelText('Metric'), { target: { value: 'mrr' } });
    await waitFor(() => expect(screen.getByTestId('cs-k-ignored-caption')).toBeInTheDocument());
    expect(screen.queryByLabelText('k')).not.toBeInTheDocument();

    // Switching back to map should not bring k=10 back (it was cleared).
    fireEvent.change(screen.getByLabelText('Metric'), { target: { value: 'map' } });
    await waitFor(() => expect(screen.getByTestId('cs-k-sublabel')).toHaveTextContent('optional'));
    const kSelect = screen.getByLabelText('k') as HTMLSelectElement;
    expect(kSelect.value).toBe('');
  });
});
