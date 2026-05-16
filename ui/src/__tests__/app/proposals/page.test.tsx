import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { type ReactNode, useEffect, useReducer } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { TooltipProvider } from '@/components/ui/tooltip';

import { server } from '../../setup';

const API_BASE = 'http://api.test';

let lastReplace = '';
let lastPush = '';
let mockedSearch = '';
// Subscribers for the useSearchParams mock; each useSearchParams() call
// registers a force-rerender callback so router.replace(url) propagates
// to React state and triggers a refetch (preserved from
// chore_proposals_list_wire_param_e2e_test). Without this the wire
// param round-trip through useProposals isn't exercised end-to-end.
const searchParamsSubscribers = new Set<() => void>();

function applyUrl(url: string) {
  // Extract the query string from a path-or-query URL emitted by
  // `useDataTableUrlState`. The hook calls router.replace('?qs') or
  // `window.location.pathname` for an empty query.
  if (url.startsWith('?')) mockedSearch = url.slice(1);
  else if (url.includes('?')) mockedSearch = url.split('?')[1] ?? '';
  else mockedSearch = '';
  searchParamsSubscribers.forEach((fn) => fn());
}

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    replace: (url: string) => {
      lastReplace = url;
      applyUrl(url);
    },
    push: (url: string) => {
      lastPush = url;
      applyUrl(url);
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
  lastPush = '';
  mockedSearch = '';
  searchParamsSubscribers.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ProposalsPage (DataTable migration — Story 3.2)', () => {
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
      http.get(`${API_BASE}/api/v1/query-templates`, () =>
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
    expect(screen.getByTestId('data-table-total-count')).toHaveTextContent('2');
  });

  it('AC-6: clicking a status filter chip updates the URL via replace()', async () => {
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
      http.get(`${API_BASE}/api/v1/query-templates`, () =>
        HttpResponse.json(
          { data: [], next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '0' } },
        ),
      ),
    );
    await renderPage();
    await waitFor(() =>
      expect(screen.getByTestId('data-table-empty-no-rows-exist')).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId('filter-chip-status-pr_opened'));
    expect(lastReplace).toContain('status=pr_opened');
  });

  it('GPT-5.5 cycle-2 A2: invalid URL ?status= is silently ignored', async () => {
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
      http.get(`${API_BASE}/api/v1/query-templates`, () =>
        HttpResponse.json(
          { data: [], next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '0' } },
        ),
      ),
    );
    await renderPage();
    await waitFor(() => expect(capturedStatusParam).toBeNull());
  });

  it('server-side source filter refetches with ?source=manual', async () => {
    let proposalHits = 0;
    let capturedSourceParam: string | null = null;
    server.use(
      http.get(`${API_BASE}/api/v1/proposals`, ({ request }) => {
        proposalHits += 1;
        const url = new URL(request.url);
        capturedSourceParam = url.searchParams.get('source');
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
          { data: filtered, next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': String(filtered.length) } },
        );
      }),
      http.get(`${API_BASE}/api/v1/clusters`, () =>
        HttpResponse.json(
          { data: [], next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '0' } },
        ),
      ),
      http.get(`${API_BASE}/api/v1/query-templates`, () =>
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

    fireEvent.click(screen.getByTestId('filter-chip-source-manual'));
    await waitFor(() => {
      expect(screen.queryByTestId('proposal-row-pStudy')).not.toBeInTheDocument();
      expect(screen.getByTestId('proposal-row-pManual')).toBeInTheDocument();
    });
    expect(proposalHits).toBe(2);
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
      http.get(`${API_BASE}/api/v1/query-templates`, () =>
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
