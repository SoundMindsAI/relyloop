// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type ReactNode } from 'react';

import { server } from '../../setup';
import {
  useOpenPR,
  useProposal,
  useProposalForStudy,
  useProposals,
  useRejectProposal,
} from '@/lib/api/proposals';

const API_BASE = 'http://api.test';

function wrapper(qc?: QueryClient) {
  const client = qc ?? new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

function proposalDetailPayload(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: 'p1',
    study_id: 's1',
    study_summary: null,
    study_trial_id: null,
    cluster: { id: 'c1', name: 'prod', engine_type: 'elasticsearch', environment: 'prod' },
    template: { id: 't1', name: 'tmpl', version: 1, engine_type: 'elasticsearch' },
    config_diff: { boost: ['1.0', '1.5'] },
    metric_delta: null,
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

describe('useProposals', () => {
  it('encodes narrowed status filter on the wire', async () => {
    let capturedUrl = '';
    server.use(
      http.get(`${API_BASE}/api/v1/proposals`, ({ request }) => {
        capturedUrl = request.url;
        return HttpResponse.json(
          { data: [], next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '0' } },
        );
      }),
    );
    const { result } = renderHook(() => useProposals({ status: 'pr_opened' }), {
      wrapper: wrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(new URL(capturedUrl).searchParams.get('status')).toBe('pr_opened');
  });

  it('honors a function-form refetchInterval (30s pulse)', async () => {
    vi.useFakeTimers();
    let hits = 0;
    server.use(
      http.get(`${API_BASE}/api/v1/proposals`, () => {
        hits += 1;
        return HttpResponse.json(
          { data: [], next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '0' } },
        );
      }),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderHook(() => useProposals({}, { refetchInterval: () => 30_000 }), {
      wrapper: wrapper(qc),
    });
    await vi.waitFor(() => expect(hits).toBeGreaterThanOrEqual(1));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_100);
    });
    await vi.waitFor(() => expect(hits).toBeGreaterThanOrEqual(2));
    vi.useRealTimers();
  });

  it('does not refetch when refetchInterval is omitted', async () => {
    vi.useFakeTimers();
    let hits = 0;
    server.use(
      http.get(`${API_BASE}/api/v1/proposals`, () => {
        hits += 1;
        return HttpResponse.json(
          { data: [], next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '0' } },
        );
      }),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderHook(() => useProposals({}), { wrapper: wrapper(qc) });
    await vi.waitFor(() => expect(hits).toBe(1));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(hits).toBe(1);
    vi.useRealTimers();
  });
});

describe('useProposalForStudy', () => {
  it('preserved verbatim — returns first pending proposal for the study or null', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/proposals`, ({ request }) => {
        const u = new URL(request.url);
        expect(u.searchParams.get('study_id')).toBe('s1');
        expect(u.searchParams.get('status')).toBe('pending');
        expect(u.searchParams.get('limit')).toBe('1');
        return HttpResponse.json(
          {
            data: [{ ...proposalDetailPayload({ study_id: 's1' }), digest: undefined }],
            next_cursor: null,
            has_more: false,
          },
          { headers: { 'X-Total-Count': '1' } },
        );
      }),
    );
    const { result } = renderHook(() => useProposalForStudy('s1'), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.id).toBe('p1');
  });
});

describe('useProposal', () => {
  it('fetches by id and returns ProposalDetail', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/proposals/p1`, () => HttpResponse.json(proposalDetailPayload())),
    );
    const { result } = renderHook(() => useProposal('p1'), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.id).toBe('p1');
  });

  it('does not refetch when refetchInterval returns false', async () => {
    vi.useFakeTimers();
    let hits = 0;
    server.use(
      http.get(`${API_BASE}/api/v1/proposals/p1`, () => {
        hits += 1;
        return HttpResponse.json(proposalDetailPayload());
      }),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderHook(() => useProposal('p1', { refetchInterval: () => false }), {
      wrapper: wrapper(qc),
    });
    await vi.waitFor(() => expect(hits).toBe(1));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(hits).toBe(1);
    vi.useRealTimers();
  });
});

describe('useOpenPR', () => {
  it('POSTs to /open_pr with empty body and invalidates active proposal + proposals queries', async () => {
    let proposalGetHits = 0;
    let listGetHits = 0;
    let postBody: unknown = undefined;
    server.use(
      http.get(`${API_BASE}/api/v1/proposals/p1`, () => {
        proposalGetHits += 1;
        return HttpResponse.json(proposalDetailPayload());
      }),
      http.get(`${API_BASE}/api/v1/proposals`, () => {
        listGetHits += 1;
        return HttpResponse.json(
          { data: [], next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '0' } },
        );
      }),
      http.post(`${API_BASE}/api/v1/proposals/p1/open_pr`, async ({ request }) => {
        postBody = await request.json();
        return HttpResponse.json(
          { proposal_id: 'p1', status: 'pending', message: 'PR creation queued' },
          { status: 202 },
        );
      }),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const Wrapper = wrapper(qc);
    // Seed both active queries first so invalidation has something to refetch.
    const detail = renderHook(() => useProposal('p1'), { wrapper: Wrapper });
    const list = renderHook(() => useProposals({}), { wrapper: Wrapper });
    await waitFor(() => expect(detail.result.current.isSuccess).toBe(true));
    await waitFor(() => expect(list.result.current.isSuccess).toBe(true));
    expect(proposalGetHits).toBe(1);
    expect(listGetHits).toBe(1);

    const { result } = renderHook(() => useOpenPR(), { wrapper: Wrapper });
    await act(async () => {
      result.current.mutate('p1');
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(postBody).toEqual({});
    // Invalidation triggers a refetch on both active queries.
    await waitFor(() => expect(proposalGetHits).toBe(2));
    await waitFor(() => expect(listGetHits).toBe(2));
  });
});

describe('useRejectProposal', () => {
  it('POSTs reason and invalidates active proposal + proposals queries on settle', async () => {
    let proposalGetHits = 0;
    let listGetHits = 0;
    let postBody: unknown = undefined;
    server.use(
      http.get(`${API_BASE}/api/v1/proposals/p1`, () => {
        proposalGetHits += 1;
        return HttpResponse.json(proposalDetailPayload());
      }),
      http.get(`${API_BASE}/api/v1/proposals`, () => {
        listGetHits += 1;
        return HttpResponse.json(
          { data: [], next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '0' } },
        );
      }),
      http.post(`${API_BASE}/api/v1/proposals/p1/reject`, async ({ request }) => {
        postBody = await request.json();
        return HttpResponse.json(
          proposalDetailPayload({ status: 'rejected', rejected_reason: 'small delta' }),
        );
      }),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const Wrapper = wrapper(qc);
    const detail = renderHook(() => useProposal('p1'), { wrapper: Wrapper });
    const list = renderHook(() => useProposals({}), { wrapper: Wrapper });
    await waitFor(() => expect(detail.result.current.isSuccess).toBe(true));
    await waitFor(() => expect(list.result.current.isSuccess).toBe(true));

    const { result } = renderHook(() => useRejectProposal(), { wrapper: Wrapper });
    await act(async () => {
      result.current.mutate({ proposalId: 'p1', reason: 'small delta' });
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(postBody).toEqual({ reason: 'small delta' });
    await waitFor(() => expect(proposalGetHits).toBe(2));
    await waitFor(() => expect(listGetHits).toBe(2));
  });

  it('on 409 INVALID_STATE_TRANSITION, mutation still invalidates so the detail query refetches', async () => {
    let proposalGetHits = 0;
    // First GET returns 'pending'; after invalidation, second GET returns 'pr_merged'.
    server.use(
      http.get(`${API_BASE}/api/v1/proposals/p1`, () => {
        proposalGetHits += 1;
        if (proposalGetHits === 1) {
          return HttpResponse.json(proposalDetailPayload({ status: 'pending' }));
        }
        return HttpResponse.json(proposalDetailPayload({ status: 'pr_merged' }));
      }),
      http.post(`${API_BASE}/api/v1/proposals/p1/reject`, () =>
        HttpResponse.json(
          {
            detail: {
              error_code: 'INVALID_STATE_TRANSITION',
              message: "proposal is in status 'pr_merged'",
              retryable: false,
            },
          },
          { status: 409 },
        ),
      ),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const Wrapper = wrapper(qc);
    const detail = renderHook(() => useProposal('p1'), { wrapper: Wrapper });
    await waitFor(() => expect(detail.result.current.isSuccess).toBe(true));
    expect(detail.result.current.data?.status).toBe('pending');

    const { result } = renderHook(() => useRejectProposal(), { wrapper: Wrapper });
    await act(async () => {
      result.current.mutate({ proposalId: 'p1', reason: null });
    });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.errorCode).toBe('INVALID_STATE_TRANSITION');
    // Invalidation still fired on error path → second GET returned pr_merged.
    await waitFor(() => expect(proposalGetHits).toBe(2));
    await waitFor(() => expect(detail.result.current.data?.status).toBe('pr_merged'));
  });
});
