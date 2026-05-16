import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { type ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { TooltipProvider } from '@/components/ui/tooltip';

import { server } from '../../../setup';

const API_BASE = 'http://api.test';

let mockedSearch = '';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(mockedSearch),
}));

vi.mock('next/link', () => ({
  default: ({ children, href, ...rest }: { children: ReactNode; href: string }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

beforeEach(() => {
  mockedSearch = '';
});

vi.mock('recharts', async () => {
  const actual: typeof import('recharts') = await vi.importActual('recharts');
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactNode }) => (
      <div style={{ width: 800, height: 240 }}>{children}</div>
    ),
  };
});

afterEach(() => vi.restoreAllMocks());

function studyCompletedPayload() {
  return {
    id: 'st1',
    name: 'demo',
    cluster_id: 'c1',
    target: 'products',
    template_id: 'tpl1',
    query_set_id: 'qs1',
    judgment_list_id: 'jl1',
    search_space: {},
    objective: { metric: 'ndcg', k: 10, direction: 'maximize' },
    config: { max_trials: 25 },
    status: 'completed',
    failed_reason: null,
    optuna_study_name: 'st1',
    parent_study_id: null,
    baseline_metric: 0.4,
    best_metric: 0.62,
    best_trial_id: 'tr1',
    created_at: '2026-05-12T00:00:00Z',
    started_at: '2026-05-12T00:01:00Z',
    completed_at: '2026-05-12T00:30:00Z',
    trials_summary: { total: 25, complete: 24, failed: 1, pruned: 0, best_primary_metric: 0.62 },
  };
}

async function renderPage(studyId = 'st1') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { StudyDetailView } = await import('@/app/studies/[id]/page');
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider delayDuration={0}>
        <StudyDetailView studyId={studyId} />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

describe('Study detail page', () => {
  it('renders header, trials table, and digest panel for a completed study', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/studies/st1`, () => HttpResponse.json(studyCompletedPayload())),
      http.get(`${API_BASE}/api/v1/studies/st1/trials`, () =>
        HttpResponse.json(
          {
            data: [
              {
                id: 'tr1',
                study_id: 'st1',
                optuna_trial_number: 1,
                params: { boost: 1.5 },
                primary_metric: 0.62,
                metrics: {},
                duration_ms: 1200,
                status: 'complete',
                error: null,
                started_at: '2026-05-12T00:05:00Z',
                ended_at: '2026-05-12T00:05:01Z',
              },
            ],
            next_cursor: null,
            has_more: false,
          },
          { headers: { 'X-Total-Count': '1' } },
        ),
      ),
      http.get(`${API_BASE}/api/v1/studies/st1/digest`, () =>
        HttpResponse.json({
          id: 'd1',
          study_id: 'st1',
          narrative: '## Summary\n\nThings improved.',
          parameter_importance: { boost: 0.71, slop: 0.32 },
          recommended_config: { boost: 1.5 },
          suggested_followups: ['try fuzziness'],
          generated_by: 'openai:gpt-4o',
          generated_at: '2026-05-12T00:30:30Z',
        }),
      ),
      http.get(`${API_BASE}/api/v1/proposals`, () =>
        HttpResponse.json(
          {
            data: [
              {
                id: 'p1',
                study_id: 'st1',
                cluster: { id: 'c1', name: 'local-es', engine_type: 'elasticsearch' },
                template: { id: 'tpl1', name: 'match-all', version: 1 },
                status: 'pending',
                pr_state: null,
                pr_url: null,
                metric_delta: null,
                created_at: '2026-05-12T00:30:00Z',
              },
            ],
            next_cursor: null,
            has_more: false,
          },
          { headers: { 'X-Total-Count': '1' } },
        ),
      ),
    );

    await renderPage();
    await waitFor(() => expect(screen.getByTestId('study-name')).toHaveTextContent('demo'));
    expect(screen.getByTestId('study-best-metric')).toHaveTextContent('0.620');
    expect(screen.getByTestId('trial-row-tr1')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId('digest-narrative')).toBeInTheDocument());
    expect(screen.getByTestId('digest-metric-delta')).toHaveTextContent('+55.0%');
    expect(screen.getByTestId('open-pr-link')).toHaveAttribute(
      'href',
      '/proposals/p1?action=open_pr',
    );
  });

  it('does not show the digest panel while a study is running', async () => {
    const running = { ...studyCompletedPayload(), status: 'running', completed_at: null };
    server.use(
      http.get(`${API_BASE}/api/v1/studies/st1`, () => HttpResponse.json(running)),
      http.get(`${API_BASE}/api/v1/studies/st1/trials`, () =>
        HttpResponse.json(
          { data: [], next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '0' } },
        ),
      ),
      http.get(`${API_BASE}/api/v1/studies/st1/digest`, () =>
        HttpResponse.json(
          {
            detail: {
              error_code: 'DIGEST_NOT_READY',
              message: 'study still running',
              retryable: false,
            },
          },
          { status: 404 },
        ),
      ),
      http.get(`${API_BASE}/api/v1/proposals`, () =>
        HttpResponse.json(
          { data: [], next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '0' } },
        ),
      ),
    );
    await renderPage();
    await waitFor(() => expect(screen.getByTestId('study-name')).toBeInTheDocument());
    // Digest narrative should be absent for a running study.
    expect(screen.queryByTestId('digest-narrative')).toBeNull();
  });
});
