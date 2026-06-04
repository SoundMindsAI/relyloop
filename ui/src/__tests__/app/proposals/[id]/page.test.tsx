// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

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
              // feat_digest_executable_followups Story 4.1: suggested_followups
              // are now {kind, rationale, search_space} dicts.
              suggested_followups: [
                { kind: 'text', rationale: 'try BM25 tweak', search_space: null },
              ],
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
      // feat_digest_executable_followups Story 5.1 / FR-12: legacy
      // `?hypothesis=` link is retired; per-card test-ids replace it.
      expect(screen.getByTestId('followup-0-card')).toBeInTheDocument();
      expect(screen.getByText('try BM25 tweak')).toBeInTheDocument();
      // Text-kind cards have NO Run button.
      expect(screen.queryByTestId('followup-0-run')).toBeNull();
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

// feat_proposal_full_param_space_view Story 1.4 — page-level integration of
// <FullParamSpacePanel>. Lifted fetches (useTemplate(proposal.template.id) +
// useStudy(study_id) for every study-backed proposal) + race-aware mount.
describe('Proposal detail page — Story 1.4 (full-param-space mount + lifted fetches)', () => {
  function templateDetail(overrides: Record<string, unknown> = {}) {
    return {
      id: 't1',
      name: 'products',
      engine_type: 'elasticsearch',
      version: 2,
      body: '{}',
      parent_id: null,
      declared_params: { boost: 'float' },
      created_at: '2026-05-12T00:00:00Z',
      ...overrides,
    };
  }

  function studyDetail(overrides: Record<string, unknown> = {}) {
    return {
      id: 's1',
      name: 'demo study',
      cluster_id: 'c1',
      target: 'products',
      template_id: 't1',
      query_set_id: 'qs1',
      judgment_list_id: 'jl1',
      search_space: { params: {} },
      objective: { metric: 'ndcg', k: 10, direction: 'maximize' },
      config: {},
      status: 'completed',
      best_metric: 0.62,
      best_trial_id: 'tr1',
      created_at: '2026-05-12T00:00:00Z',
      ...overrides,
    };
  }

  it('Test 1 (AC-1): study-backed proposal mounts the panel with tunedChanged + untuned groups', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/proposals/p1`, () =>
        HttpResponse.json(
          proposalDetailPayload({
            study_id: 's1',
            config_diff: { boost: { from: 1, to: 2.5 } },
            digest: {
              id: 'd1',
              narrative: '## Summary',
              parameter_importance: {},
              recommended_config: {},
              suggested_followups: [
                {
                  kind: 'swap_template',
                  rationale: 'try other tpl',
                  search_space: null,
                  template_id: 't9',
                },
              ],
              generated_at: '2026-05-12T00:00:00Z',
            },
          }),
        ),
      ),
      http.get(`${API_BASE}/api/v1/studies/s1`, () =>
        HttpResponse.json(studyDetail({ search_space: { params: { boost: { min: 0, max: 3 } } } })),
      ),
      http.get(`${API_BASE}/api/v1/query-templates/t1`, () =>
        HttpResponse.json(templateDetail({ declared_params: { boost: 'float', other: 'int' } })),
      ),
      // The swap_template card lazily fetches t9; provide a stub so it doesn't 404-noise.
      http.get(`${API_BASE}/api/v1/query-templates/t9`, () =>
        HttpResponse.json(templateDetail({ id: 't9', declared_params: { other: 'int' } })),
      ),
    );
    await renderPage('p1');
    await waitFor(() =>
      expect(screen.getByTestId('param-space-row-tuned_changed-boost')).toBeInTheDocument(),
    );
    // `other` is declared but NOT in search_space → untuned.
    expect(screen.getByTestId('param-space-row-untuned-other')).toBeInTheDocument();
  });

  it('Test 2 (AC-3): manual proposal (study_id null) mounts as soon as the template resolves', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/proposals/pm`, () =>
        HttpResponse.json(
          proposalDetailPayload({
            id: 'pm',
            study_id: null,
            study_summary: null,
            config_diff: { boost: { from: 1, to: 2 } },
            digest: null,
          }),
        ),
      ),
      http.get(`${API_BASE}/api/v1/query-templates/t1`, () =>
        HttpResponse.json(
          templateDetail({ declared_params: { boost: 'float', title_weight: 'float' } }),
        ),
      ),
    );
    await renderPage('pm');
    await waitFor(() =>
      expect(screen.getByTestId('param-space-row-tuned_changed-boost')).toBeInTheDocument(),
    );
    // No source study → tunedUnchanged group absent; title_weight (declared, not tuned) → untuned.
    expect(screen.queryByTestId('param-space-group-tuned_unchanged')).toBeNull();
    expect(screen.getByTestId('param-space-row-untuned-title_weight')).toBeInTheDocument();
  });

  it('Test 3 (AC-4): template fetch 404 → panel does NOT mount, rest of page renders', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/proposals/p404`, () =>
        HttpResponse.json(
          proposalDetailPayload({ id: 'p404', study_id: null, study_summary: null, digest: null }),
        ),
      ),
      http.get(`${API_BASE}/api/v1/query-templates/t1`, () =>
        HttpResponse.json(
          { detail: { error_code: 'TEMPLATE_NOT_FOUND', message: 'gone', retryable: false } },
          { status: 404 },
        ),
      ),
    );
    await renderPage('p404');
    // ConfigDiffPanel + metric-delta + PR panel still render unaffected.
    await waitFor(() => expect(screen.getByTestId('config-diff-table')).toBeInTheDocument());
    expect(screen.getByText('Metric delta')).toBeInTheDocument();
    expect(screen.getByTestId('open-pr-button')).toBeInTheDocument();
    // Panel did NOT mount.
    expect(screen.queryByTestId('param-space-group-tuned_changed')).toBeNull();
    expect(screen.queryByTestId('param-space-empty')).toBeNull();
  });

  it('Test 4 (AC-11): race-aware gating — template resolves first, panel waits for study to settle', async () => {
    let resolveStudy!: (resp: Response) => void;
    const studyPromise = new Promise<Response>((r) => {
      resolveStudy = r;
    });
    // Dual-deferred: defer BOTH template and study so the test deterministically
    // controls the resolution order. This avoids the vacuous-pass risk where an
    // immediate template might still be pending when we assert "panel absent"
    // (i.e. the panel would be absent because BOTH gates are unmet, not because
    // of the race-specific gate).
    let resolveTemplate!: (resp: Response) => void;
    const templatePromise = new Promise<Response>((r) => {
      resolveTemplate = r;
    });
    server.use(
      http.get(`${API_BASE}/api/v1/proposals/p1`, () =>
        HttpResponse.json(
          proposalDetailPayload({
            study_id: 's1',
            config_diff: {},
            digest: null,
          }),
        ),
      ),
      http.get(`${API_BASE}/api/v1/query-templates/t1`, async () => templatePromise),
      http.get(`${API_BASE}/api/v1/studies/s1`, async () => studyPromise),
    );

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { ProposalDetailView } = await import('@/app/proposals/[id]/page');
    render(
      <QueryClientProvider client={qc}>
        <TooltipProvider delayDuration={0}>
          <ProposalDetailView proposalId="p1" />
        </TooltipProvider>
      </QueryClientProvider>,
    );

    // Proposal resolves; both template + study held pending. (config_diff is
    // empty here, so the ConfigDiffPanel shows its empty state, not the table.)
    await waitFor(() => expect(screen.getByText('Proposal detail')).toBeInTheDocument());

    // Step 1: resolve the TEMPLATE only — study remains pending. This is the
    // race-specific state the FR-4 gating defends against.
    resolveTemplate(HttpResponse.json(templateDetail({ declared_params: { foo: 'float' } })));
    await waitFor(() =>
      expect(qc.getQueryState(['query-templates', 't1'])?.status).toBe('success'),
    );
    // Race-specific assertion: template ready, study pending → panel ABSENT.
    // Crucially assert the `untuned` group + the `foo` untuned row are absent:
    // if the panel mounted prematurely (searchSpaceParams undefined while the
    // study is pending), `foo` would mis-classify as untuned and render here.
    // The tuned_unchanged + empty checks alone would pass even on a premature
    // mount (foo→untuned), so they don't catch the race (final-review FF1).
    expect(screen.queryByTestId('param-space-group-untuned')).toBeNull();
    expect(screen.queryByTestId('param-space-row-untuned-foo')).toBeNull();
    expect(screen.queryByTestId('param-space-group-tuned_unchanged')).toBeNull();
    expect(screen.queryByTestId('param-space-empty')).toBeNull();

    // Step 2: resolve the study fetch — panel now mounts with correct classification.
    resolveStudy(
      HttpResponse.json(studyDetail({ search_space: { params: { foo: { min: 0, max: 1 } } } })),
    );
    await waitFor(() =>
      expect(screen.getByTestId('param-space-row-tuned_unchanged-foo')).toBeInTheDocument(),
    );
  });

  it('Test 5 (FR-3 regression guard): study proposal with NO actionable followups still fetches the study', async () => {
    // Cycle-3 F1: without lifting the useStudy gate, a text-only digest would
    // leave search_space undefined and mis-classify `foo` as untuned.
    server.use(
      http.get(`${API_BASE}/api/v1/proposals/p2`, () =>
        HttpResponse.json(
          proposalDetailPayload({
            id: 'p2',
            study_id: 's2',
            config_diff: {},
            digest: {
              id: 'd2',
              narrative: '## Summary',
              parameter_importance: {},
              recommended_config: {},
              suggested_followups: [{ kind: 'text', rationale: 'tweak BM25', search_space: null }],
              generated_at: '2026-05-12T00:00:00Z',
            },
          }),
        ),
      ),
      http.get(`${API_BASE}/api/v1/studies/s2`, () =>
        HttpResponse.json(
          studyDetail({ id: 's2', search_space: { params: { foo: { min: 0, max: 1 } } } }),
        ),
      ),
      http.get(`${API_BASE}/api/v1/query-templates/t1`, () =>
        HttpResponse.json(templateDetail({ declared_params: { foo: 'float', bar: 'int' } })),
      ),
    );
    await renderPage('p2');
    // foo is in search_space → tunedUnchanged (NOT untuned). This fails if the
    // useStudy lift were missing.
    await waitFor(() =>
      expect(screen.getByTestId('param-space-row-tuned_unchanged-foo')).toBeInTheDocument(),
    );
    expect(screen.queryByTestId('param-space-row-untuned-foo')).toBeNull();
    // bar is declared but NOT in search_space → untuned.
    expect(screen.getByTestId('param-space-row-untuned-bar')).toBeInTheDocument();
  });

  it('Test 6 (FR-7 edge A): source-study fetch error → panel still mounts, tunedUnchanged empty', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/proposals/p3`, () =>
        HttpResponse.json(
          proposalDetailPayload({
            id: 'p3',
            study_id: 's3',
            config_diff: {},
            digest: null,
          }),
        ),
      ),
      http.get(`${API_BASE}/api/v1/studies/s3`, () =>
        HttpResponse.json(
          { detail: { error_code: 'STUDY_NOT_FOUND', message: 'gone', retryable: false } },
          { status: 404 },
        ),
      ),
      http.get(`${API_BASE}/api/v1/query-templates/t1`, () =>
        HttpResponse.json(templateDetail({ declared_params: { foo: 'float', bar: 'int' } })),
      ),
    );
    await renderPage('p3');
    // Study errored → searchSpaceParams undefined → every declared param is untuned.
    await waitFor(() =>
      expect(screen.getByTestId('param-space-row-untuned-foo')).toBeInTheDocument(),
    );
    expect(screen.getByTestId('param-space-row-untuned-bar')).toBeInTheDocument();
    expect(screen.queryByTestId('param-space-group-tuned_unchanged')).toBeNull();
  });
});
