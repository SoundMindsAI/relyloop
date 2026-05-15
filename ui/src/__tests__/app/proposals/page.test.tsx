import { http, HttpResponse } from 'msw';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { type ReactNode, useEffect, useReducer } from 'react';

import { TooltipProvider } from '@/components/ui/tooltip';

import { server } from '../../setup';

const API_BASE = 'http://api.test';

let lastReplace = '';
let mockedSearch = '';
// Subscribers for the useSearchParams mock; each useSearchParams() call
// registers a force-rerender callback so router.replace(url) propagates
// to React state and triggers a refetch (per
// chore_proposals_list_wire_param_e2e_test). Without this, the wire
// param round-trip through useProposals isn't exercised end-to-end.
const searchParamsSubscribers = new Set<() => void>();

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    replace: (url: string) => {
      lastReplace = url;
      mockedSearch = url.includes('?') ? (url.split('?')[1] ?? '') : '';
      // Notify subscribers OUTSIDE React's lifecycle; the consuming
      // useEffect / useState will pick up the change on the next render.
      searchParamsSubscribers.forEach((fn) => fn());
    },
  }),
  useSearchParams: () => {
    const [, force] = useReducer((x: number) => x + 1, 0);
    useEffect(() => {
      searchParamsSubscribers.add(force);
      return () => {
        searchParamsSubscribers.delete(force);
      };
    }, []);
    return new URLSearchParams(mockedSearch);
  },
}));

vi.mock('next/link', () => ({
  default: ({ children, href }: { children: ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

async function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { default: ProposalsPage } = await import('@/app/proposals/page');
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider delayDuration={0}>
        <ProposalsPage />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

function proposalRow(overrides: Record<string, unknown> = {}) {
  return {
    id: 'p1',
    study_id: 's1',
    cluster: { id: 'c1', name: 'prod-es', engine_type: 'elasticsearch', environment: 'prod' },
    template: { id: 't1', name: 'products', version: 1, engine_type: 'elasticsearch' },
    status: 'pending',
    pr_state: null,
    pr_url: null,
    metric_delta: null,
    created_at: '2026-05-12T00:00:00Z',
    ...overrides,
  };
}

beforeEach(() => {
  lastReplace = '';
  mockedSearch = '';
  searchParamsSubscribers.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ProposalsPage', () => {
  it('renders rows from the API and shows total count', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/proposals`, () =>
        HttpResponse.json(
          {
            data: [proposalRow({ id: 'pA' }), proposalRow({ id: 'pB', study_id: null })],
            next_cursor: null,
            has_more: false,
          },
          { headers: { 'X-Total-Count': '2' } },
        ),
      ),
      http.get(`${API_BASE}/api/v1/clusters`, () =>
        HttpResponse.json(
          { data: [], next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '0' } },
        ),
      ),
    );
    await renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('proposal-row-pA')).toBeInTheDocument();
      expect(screen.getByTestId('proposal-row-pB')).toBeInTheDocument();
    });
    expect(screen.getByTestId('total-count')).toHaveTextContent('2');
  });

  it('AC-6: clicking a status chip updates the URL', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/proposals`, () =>
        HttpResponse.json(
          { data: [], next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '0' } },
        ),
      ),
      http.get(`${API_BASE}/api/v1/clusters`, () =>
        HttpResponse.json(
          { data: [], next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '0' } },
        ),
      ),
    );
    await renderPage();
    await waitFor(() => expect(screen.getByTestId('empty-state')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('proposal-status-chip-pr_opened'));
    expect(lastReplace).toBe('/proposals?status=pr_opened');
  });

  it('AC-6: clicking a status chip sends ?status= on the next backend request', async () => {
    // chore_proposals_list_wire_param_e2e_test: prove the click → router.replace
    // → useSearchParams re-render → useProposals queryKey change → wire-param
    // round trip works end-to-end, not just at the router.replace boundary.
    // The improved useSearchParams mock above (subscribers + useReducer)
    // propagates URL changes into React state so this test exercises the
    // full client-side flow.
    const capturedStatusParams: (string | null)[] = [];
    server.use(
      http.get(`${API_BASE}/api/v1/proposals`, ({ request }) => {
        const url = new URL(request.url);
        capturedStatusParams.push(url.searchParams.get('status'));
        return HttpResponse.json(
          { data: [], next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '0' } },
        );
      }),
      http.get(`${API_BASE}/api/v1/clusters`, () =>
        HttpResponse.json(
          { data: [], next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '0' } },
        ),
      ),
    );
    await renderPage();
    await waitFor(() => expect(capturedStatusParams.length).toBeGreaterThan(0));
    expect(capturedStatusParams[0]).toBeNull();

    fireEvent.click(screen.getByTestId('proposal-status-chip-pr_opened'));
    // The router.replace mock propagates to useSearchParams subscribers,
    // useProposals's queryKey changes, react-query refetches with the
    // new ?status= param.
    await waitFor(() => {
      expect(capturedStatusParams).toContain('pr_opened');
    });
  });

  it('AC-6: status=all chip clears the URL param', async () => {
    mockedSearch = 'status=pending';
    server.use(
      http.get(`${API_BASE}/api/v1/proposals`, () =>
        HttpResponse.json(
          { data: [], next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '0' } },
        ),
      ),
      http.get(`${API_BASE}/api/v1/clusters`, () =>
        HttpResponse.json(
          { data: [], next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '0' } },
        ),
      ),
    );
    await renderPage();
    await waitFor(() => expect(screen.getByTestId('empty-state')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('proposal-status-chip-all'));
    expect(lastReplace).toBe('/proposals');
  });

  it('GPT-5.5 cycle-2 A2: invalid URL ?status= is silently ignored (not sent to backend)', async () => {
    mockedSearch = 'status=invented';
    let capturedStatusParam: string | null | undefined;
    server.use(
      http.get(`${API_BASE}/api/v1/proposals`, ({ request }) => {
        capturedStatusParam = new URL(request.url).searchParams.get('status');
        return HttpResponse.json(
          { data: [], next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '0' } },
        );
      }),
      http.get(`${API_BASE}/api/v1/clusters`, () =>
        HttpResponse.json(
          { data: [], next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '0' } },
        ),
      ),
    );
    await renderPage();
    await waitFor(() => expect(screen.getByTestId('empty-state')).toBeInTheDocument());
    // 'invented' is not in PROPOSAL_STATUS_VALUES → narrowed to undefined → no wire param.
    expect(capturedStatusParam).toBeNull();
    // The chip group falls back to 'all' active.
    expect(screen.getByTestId('proposal-status-chip-all')).toHaveAttribute('data-active', 'true');
  });

  it('server-side source filter refetches with ?source=manual', async () => {
    let proposalHits = 0;
    let capturedSourceParam: string | null = null;
    server.use(
      http.get(`${API_BASE}/api/v1/proposals`, ({ request }) => {
        proposalHits += 1;
        const url = new URL(request.url);
        capturedSourceParam = url.searchParams.get('source');
        // Server-side filter (per chore_proposals_source_filter_server_side):
        // backend trims rows by ?source= so pagination + X-Total-Count stay
        // consistent. We mirror that here so the test matches the production
        // contract.
        const allRows = [
          proposalRow({ id: 'pStudy', study_id: 's1' }),
          proposalRow({ id: 'pManual', study_id: null }),
        ];
        const filtered =
          capturedSourceParam === 'study'
            ? allRows.filter((r) => r.study_id != null)
            : capturedSourceParam === 'manual'
              ? allRows.filter((r) => r.study_id == null)
              : allRows;
        return HttpResponse.json(
          {
            data: filtered,
            next_cursor: null,
            has_more: false,
          },
          { headers: { 'X-Total-Count': String(filtered.length) } },
        );
      }),
      http.get(`${API_BASE}/api/v1/clusters`, () =>
        HttpResponse.json(
          { data: [], next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '0' } },
        ),
      ),
    );
    await renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('proposal-row-pStudy')).toBeInTheDocument();
      expect(screen.getByTestId('proposal-row-pManual')).toBeInTheDocument();
    });
    expect(proposalHits).toBe(1);
    expect(capturedSourceParam).toBeNull();

    fireEvent.click(screen.getByTestId('proposal-source-chip-manual'));
    await waitFor(() => {
      expect(screen.queryByTestId('proposal-row-pStudy')).not.toBeInTheDocument();
      expect(screen.getByTestId('proposal-row-pManual')).toBeInTheDocument();
    });
    expect(proposalHits).toBe(2); // a new wire call goes out with ?source=manual
    expect(capturedSourceParam).toBe('manual');
  });

  it('FR-1: 30s pulse-refetch when a visible row is pr_opened+open', async () => {
    vi.useFakeTimers();
    let proposalHits = 0;
    server.use(
      http.get(`${API_BASE}/api/v1/proposals`, () => {
        proposalHits += 1;
        return HttpResponse.json(
          {
            data: [proposalRow({ id: 'pOpen', status: 'pr_opened', pr_state: 'open' })],
            next_cursor: null,
            has_more: false,
          },
          { headers: { 'X-Total-Count': '1' } },
        );
      }),
      http.get(`${API_BASE}/api/v1/clusters`, () =>
        HttpResponse.json(
          { data: [], next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '0' } },
        ),
      ),
    );
    await renderPage();
    await vi.waitFor(() => expect(proposalHits).toBeGreaterThanOrEqual(1));
    const first = proposalHits;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_100);
    });
    await vi.waitFor(() => expect(proposalHits).toBeGreaterThan(first));
    vi.useRealTimers();
  });
});
