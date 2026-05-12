import { http, HttpResponse } from 'msw';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type ReactNode } from 'react';

import { server } from '../../../setup';

const API_BASE = 'http://api.test';

vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ replace: () => {} }),
}));

vi.mock('next/link', () => ({
  default: ({ children, href, ...rest }: { children: ReactNode; href: string }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

afterEach(() => vi.restoreAllMocks());

function proposalDetailPayload(overrides: Record<string, unknown> = {}) {
  return {
    id: 'p1',
    study_id: 's1',
    study_summary: {
      id: 's1',
      name: 'demo study',
      status: 'completed',
      best_metric: 0.62,
      best_trial_id: 'tr1',
      query_set: { id: 'qs1', name: 'qs', query_count: 25 },
      judgment_list: { id: 'jl1', name: 'jl', status: 'complete' },
    },
    study_trial_id: 'tr1',
    cluster: { id: 'c1', name: 'prod-es', engine_type: 'elasticsearch', environment: 'prod' },
    template: { id: 't1', name: 'products', version: 2, engine_type: 'elasticsearch' },
    config_diff: { boost: ['1.0', '1.5'], slop: ['0', '2'] },
    metric_delta: {
      primary: 'ndcg@10',
      baseline: 0.4,
      best: 0.62,
      delta_pct: 55,
    },
    status: 'pending',
    pr_url: null,
    pr_state: null,
    pr_merged_at: null,
    pr_open_error: null,
    rejected_reason: null,
    digest: null,
    created_at: '2026-05-12T00:00:00Z',
    ...overrides,
  };
}

async function renderPage(proposalId = 'p1') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { ProposalDetailView } = await import('@/app/proposals/[id]/page');
  return render(
    <QueryClientProvider client={qc}>
      <ProposalDetailView proposalId={proposalId} />
    </QueryClientProvider>,
  );
}

describe('Proposal detail page (Story 3.1 shell)', () => {
  it('renders header + config-diff + metric-delta + followups for a pending proposal with followups', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/proposals/p1`, () =>
        HttpResponse.json(
          proposalDetailPayload({
            digest: {
              id: 'd1',
              narrative: '## Summary',
              parameter_importance: {},
              recommended_config: {},
              suggested_followups: ['try BM25 tweak'],
              generated_at: '2026-05-12T00:00:00Z',
            },
          }),
        ),
      ),
    );
    await renderPage('p1');
    await waitFor(() => {
      expect(screen.getByText('Proposal detail')).toBeInTheDocument();
      expect(screen.getByText('prod-es')).toBeInTheDocument();
      expect(screen.getByText('products')).toBeInTheDocument();
      expect(screen.getByTestId('config-diff-row-boost')).toBeInTheDocument();
      expect(screen.getByTestId('config-diff-row-slop')).toBeInTheDocument();
      expect(screen.getByTestId('metric-delta-pct')).toHaveTextContent('(+55.0%)');
      expect(screen.getByTestId('suggested-followups-list')).toBeInTheDocument();
      expect(screen.getByTestId('followup-0-create-study')).toHaveAttribute(
        'href',
        '/studies?hypothesis=try%20BM25%20tweak',
      );
    });
  });

  it('AC-4: renders the red Alert when status=pending and pr_open_error is set', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/proposals/p2`, () =>
        HttpResponse.json(
          proposalDetailPayload({
            id: 'p2',
            status: 'pending',
            pr_open_error: 'Branch already exists',
          }),
        ),
      ),
    );
    await renderPage('p2');
    await waitFor(() => {
      expect(screen.getByTestId('proposal-error-alert')).toBeInTheDocument();
      expect(screen.getByText('Branch already exists')).toBeInTheDocument();
    });
  });

  it('does NOT render the Alert when status=pr_opened (defensive)', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/proposals/p3`, () =>
        HttpResponse.json(
          proposalDetailPayload({
            id: 'p3',
            status: 'pr_opened',
            pr_state: 'open',
            pr_url: 'https://github.com/example/repo/pull/42',
            pr_open_error: 'stale error from earlier attempt',
          }),
        ),
      ),
    );
    await renderPage('p3');
    await waitFor(() => expect(screen.getByText('Proposal detail')).toBeInTheDocument());
    expect(screen.queryByTestId('proposal-error-alert')).not.toBeInTheDocument();
  });

  it('renders the Proposal-not-found empty state on 404 PROPOSAL_NOT_FOUND', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/proposals/missing`, () =>
        HttpResponse.json(
          {
            detail: {
              error_code: 'PROPOSAL_NOT_FOUND',
              message: 'proposal missing not found',
              retryable: false,
            },
          },
          { status: 404 },
        ),
      ),
    );
    await renderPage('missing');
    await waitFor(() => expect(screen.getByText('Proposal not found')).toBeInTheDocument());
  });

  it('renders "No metric delta recorded." when metric_delta is null', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/proposals/p4`, () =>
        HttpResponse.json(proposalDetailPayload({ id: 'p4', metric_delta: null })),
      ),
    );
    await renderPage('p4');
    await waitFor(() => expect(screen.getByTestId('metric-delta-empty')).toBeInTheDocument());
  });

  it('does NOT render the followups section when digest is null', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/proposals/p5`, () =>
        HttpResponse.json(proposalDetailPayload({ id: 'p5', digest: null })),
      ),
    );
    await renderPage('p5');
    await waitFor(() => expect(screen.getByText('Proposal detail')).toBeInTheDocument());
    expect(screen.queryByTestId('suggested-followups-list')).not.toBeInTheDocument();
  });
});
