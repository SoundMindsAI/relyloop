import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type ReactNode } from 'react';

import { TooltipProvider } from '@/components/ui/tooltip';

import { server } from '../../../setup';

const API_BASE = 'http://api.test';

let mockedSearch = '';
let lastReplace = '';

vi.mock('next/navigation', () => ({
  usePathname: () => '/test',
  useSearchParams: () => new URLSearchParams(mockedSearch),
  useRouter: () => ({
    replace: (url: string) => {
      lastReplace = url;
    },
  }),
}));

beforeEach(() => {
  mockedSearch = '';
  lastReplace = '';
});

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
      <TooltipProvider delayDuration={0}>
        <ProposalDetailView proposalId={proposalId} />
      </TooltipProvider>
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

describe('Proposal detail page — Story 3.2 (PR panel + polling + auto-trigger)', () => {
  it('AC-1: clicking Open PR enqueues, polls at 3s, then flips to pr_opened on next GET', async () => {
    vi.useFakeTimers();
    let proposalGetHits = 0;
    let postHits = 0;
    server.use(
      http.get(`${API_BASE}/api/v1/proposals/p1`, () => {
        proposalGetHits += 1;
        // First GET: pending. After mutation, subsequent GETs: pr_opened+open.
        if (proposalGetHits === 1) {
          return HttpResponse.json(proposalDetailPayload({ status: 'pending' }));
        }
        return HttpResponse.json(
          proposalDetailPayload({
            status: 'pr_opened',
            pr_state: 'open',
            pr_url: 'https://github.com/foo/bar/pull/42',
          }),
        );
      }),
      http.post(`${API_BASE}/api/v1/proposals/p1/open_pr`, () => {
        postHits += 1;
        return HttpResponse.json(
          { proposal_id: 'p1', status: 'pending', message: 'PR creation queued' },
          { status: 202 },
        );
      }),
    );
    await renderPage('p1');
    await vi.waitFor(() => expect(proposalGetHits).toBe(1));
    await vi.waitFor(() => expect(screen.getByTestId('open-pr-button')).toBeInTheDocument());

    await act(async () => {
      screen.getByTestId('open-pr-button').click();
    });
    await vi.waitFor(() => expect(postHits).toBe(1));

    // Advance 3.1s — the 3s poll should fire at least once.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3_100);
    });
    await vi.waitFor(() => expect(proposalGetHits).toBeGreaterThanOrEqual(2));
    // Now status flipped to pr_opened → PR link should render, button gone.
    await vi.waitFor(() => expect(screen.queryByTestId('open-pr-button')).not.toBeInTheDocument());
    expect(screen.getByTestId('pr-link')).toHaveAttribute(
      'href',
      'https://github.com/foo/bar/pull/42',
    );
    vi.useRealTimers();
  });

  it('AC-3: 30s steady-state polling fires when status=pr_opened+pr_state=open', async () => {
    vi.useFakeTimers();
    let proposalGetHits = 0;
    server.use(
      http.get(`${API_BASE}/api/v1/proposals/p1`, () => {
        proposalGetHits += 1;
        return HttpResponse.json(
          proposalDetailPayload({
            status: 'pr_opened',
            pr_state: 'open',
            pr_url: 'https://github.com/foo/bar/pull/42',
          }),
        );
      }),
    );
    await renderPage('p1');
    await vi.waitFor(() => expect(proposalGetHits).toBe(1));
    const first = proposalGetHits;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_100);
    });
    await vi.waitFor(() => expect(proposalGetHits).toBeGreaterThan(first));
    vi.useRealTimers();
  });

  it('auto-trigger: ?action=open_pr + status=pending fires the mutation once and replaces the URL', async () => {
    mockedSearch = 'action=open_pr';
    let proposalGetHits = 0;
    let postHits = 0;
    server.use(
      http.get(`${API_BASE}/api/v1/proposals/p1`, () => {
        proposalGetHits += 1;
        return HttpResponse.json(proposalDetailPayload({ status: 'pending' }));
      }),
      http.post(`${API_BASE}/api/v1/proposals/p1/open_pr`, () => {
        postHits += 1;
        return HttpResponse.json(
          { proposal_id: 'p1', status: 'pending', message: 'PR creation queued' },
          { status: 202 },
        );
      }),
    );
    await renderPage('p1');
    await waitFor(() => expect(postHits).toBe(1));
    expect(lastReplace).toBe('/proposals/p1');
    // Sanity: not double-fired even after later renders.
    await waitFor(() => expect(proposalGetHits).toBeGreaterThanOrEqual(1));
    expect(postHits).toBe(1);
  });

  it('auto-trigger does NOT fire when status is already pr_opened', async () => {
    mockedSearch = 'action=open_pr';
    let postHits = 0;
    server.use(
      http.get(`${API_BASE}/api/v1/proposals/p1`, () =>
        HttpResponse.json(
          proposalDetailPayload({
            status: 'pr_opened',
            pr_state: 'open',
            pr_url: 'https://github.com/foo/bar/pull/42',
          }),
        ),
      ),
      http.post(`${API_BASE}/api/v1/proposals/p1/open_pr`, () => {
        postHits += 1;
        return HttpResponse.json(
          { proposal_id: 'p1', status: 'pending', message: 'noop' },
          { status: 202 },
        );
      }),
    );
    await renderPage('p1');
    await waitFor(() => expect(screen.getByTestId('pr-link')).toBeInTheDocument());
    expect(postHits).toBe(0);
  });

  it('60s safety cap: worker never writes back → polling stops, button re-enables for retry (Story 3.2 DoD)', async () => {
    vi.useFakeTimers();
    let proposalGetHits = 0;
    let postHits = 0;
    server.use(
      http.get(`${API_BASE}/api/v1/proposals/p1`, () => {
        proposalGetHits += 1;
        // Always return pending — the simulated worker never writes back.
        return HttpResponse.json(proposalDetailPayload({ status: 'pending' }));
      }),
      http.post(`${API_BASE}/api/v1/proposals/p1/open_pr`, () => {
        postHits += 1;
        return HttpResponse.json(
          { proposal_id: 'p1', status: 'pending', message: 'PR creation queued' },
          { status: 202 },
        );
      }),
    );
    await renderPage('p1');
    await vi.waitFor(() => expect(proposalGetHits).toBe(1));
    await vi.waitFor(() => expect(screen.getByTestId('open-pr-button')).toBeInTheDocument());

    await act(async () => {
      screen.getByTestId('open-pr-button').click();
    });
    await vi.waitFor(() => expect(postHits).toBe(1));

    // 3s polling fires while the safety cap counts down.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });
    const hitsAt15s = proposalGetHits;
    expect(hitsAt15s).toBeGreaterThanOrEqual(5); // ~5 ticks within 15s

    // Advance past the 60s cap. Polling continues briefly until the next
    // 3s tick reads the now-flipped postOpenPrPolling=false. Round to 65s.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(50_000);
    });
    const hitsAt65s = proposalGetHits;
    // Cumulative ticks bounded at ~21 (60s / 3s + initial fetch). Allow some
    // slop for timer queue ordering.
    expect(hitsAt65s).toBeLessThan(30);

    // Now advance another 30s and confirm polling has actually stopped.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(proposalGetHits).toBeLessThanOrEqual(hitsAt65s + 1);

    // Button re-enables because effectivePollingFlag is false.
    await vi.waitFor(() => expect(screen.getByTestId('open-pr-button')).not.toBeDisabled());
    vi.useRealTimers();
  });

  it('Open-PR error-toast contract: 503 / 422 errors reach the global MutationCache.onError with the expected ApiError.errorCode (Story 3.2 DoD)', async () => {
    // The page's useOpenPR mutation must NOT set meta.suppressGlobalErrorToast,
    // so all three required backend errors land in the global handler. We
    // assert against the ApiError.errorCode contract (not the formatted
    // toast string) per GPT-5.5 cycle-1 B6.
    const { MutationCache, QueryClient: QC } = await import('@tanstack/react-query');
    const errorsSeen: Array<{ code: string }> = [];
    const mc = new MutationCache({
      onError: (err) => {
        const e = err as { errorCode?: string };
        errorsSeen.push({ code: e.errorCode ?? 'UNKNOWN' });
      },
    });
    const qc = new QC({
      defaultOptions: { queries: { retry: false } },
      mutationCache: mc,
    });

    // Sequence: 3 sequential calls return GITHUB_NOT_CONFIGURED (503),
    // CLUSTER_HAS_NO_CONFIG_REPO (422), QUEUE_UNAVAILABLE (503).
    let call = 0;
    // Marked retryable=false in this test so the api-client doesn't fire its
    // 4-attempt 503+retryable backoff (1+2+4 s). The retry behavior itself is
    // covered by __tests__/lib/api-client.test.ts; here we only assert the
    // error code reaches the global MutationCache.onError handler.
    const errors = [
      { code: 'GITHUB_NOT_CONFIGURED', status: 503, retryable: false },
      { code: 'CLUSTER_HAS_NO_CONFIG_REPO', status: 422, retryable: false },
      { code: 'QUEUE_UNAVAILABLE', status: 503, retryable: false },
    ];
    server.use(
      http.get(`${API_BASE}/api/v1/proposals/p1`, () =>
        HttpResponse.json(proposalDetailPayload({ status: 'pending' })),
      ),
      http.post(`${API_BASE}/api/v1/proposals/p1/open_pr`, () => {
        const e = errors[call] ?? errors[2];
        call += 1;
        if (!e) {
          // Defensive: TS narrowing — shouldn't happen with our index guard.
          return HttpResponse.json(errors[2], { status: 500 });
        }
        return HttpResponse.json(
          { detail: { error_code: e.code, message: 'x', retryable: e.retryable } },
          { status: e.status },
        );
      }),
    );

    const { ProposalDetailView } = await import('@/app/proposals/[id]/page');
    const { QueryClientProvider } = await import('@tanstack/react-query');
    render(
      <QueryClientProvider client={qc}>
        <TooltipProvider delayDuration={0}>
          <ProposalDetailView proposalId="p1" />
        </TooltipProvider>
      </QueryClientProvider>,
    );

    await waitFor(() => expect(screen.getByTestId('open-pr-button')).toBeInTheDocument());

    // Click 3 times across 3 separate renders to exercise the 3 error paths.
    for (const expected of errors) {
      await act(async () => {
        screen.getByTestId('open-pr-button').click();
      });
      await waitFor(() => expect(errorsSeen.some((e) => e.code === expected.code)).toBe(true));
    }

    expect(errorsSeen.map((e) => e.code)).toEqual([
      'GITHUB_NOT_CONFIGURED',
      'CLUSTER_HAS_NO_CONFIG_REPO',
      'QUEUE_UNAVAILABLE',
    ]);
  });
});
