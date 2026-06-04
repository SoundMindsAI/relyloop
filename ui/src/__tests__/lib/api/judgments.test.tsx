// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * feat_study_wizard_inline_judgment_generation Story 1.3 — proves the
 * `useJudgmentLists(filter, { refetchInterval })` plumbing is actually wired
 * through React Query (not bypassed by a component-boundary mock):
 *  - AC-5: while a list is `generating`, a conditional refetchInterval fires a
 *    SECOND fetch; once all lists are `complete`, polling stops.
 *  - the refetchInterval option does NOT leak into the request params / query key.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook } from '@testing-library/react';
import { type ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { apiClient } from '@/lib/api-client';
import { useJudgmentLists } from '@/lib/api/judgments';

function wrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

function page(status: 'generating' | 'complete' | 'failed') {
  return {
    data: {
      data: [
        {
          id: 'jl1',
          name: 'demo',
          description: null,
          query_set_id: 'qs1',
          cluster_id: 'c1',
          status,
          created_at: '2026-05-12T00:00:00Z',
        },
      ],
      next_cursor: null,
      has_more: false,
    },
    headers: new Headers([['X-Total-Count', '1']]),
  };
}

const POLL = (q: { state: { data?: { data?: { status: string }[] } } }) =>
  q.state.data?.data?.some((j) => j.status === 'generating') ? 4000 : false;

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe('useJudgmentLists — conditional refetchInterval (Story 1.3)', () => {
  it('AC-5: polls a second time while generating, then stops once complete', async () => {
    vi.useFakeTimers();
    const getSpy = vi
      .spyOn(apiClient, 'get')
      .mockResolvedValueOnce(page('generating') as never) // first fetch: generating
      .mockResolvedValue(page('complete') as never); // poll fetch: complete

    renderHook(() => useJudgmentLists({ query_set_id: 'qs1' }, { refetchInterval: POLL }), {
      wrapper: wrapper(),
    });

    // First fetch resolves (data = generating).
    await vi.advanceTimersByTimeAsync(0);
    expect(getSpy).toHaveBeenCalledTimes(1);

    // Generating → refetchInterval = 4000ms → a SECOND fetch fires.
    await vi.advanceTimersByTimeAsync(4000);
    expect(getSpy).toHaveBeenCalledTimes(2);

    // Data is now complete → refetchInterval = false → no further polling.
    await vi.advanceTimersByTimeAsync(12_000);
    expect(getSpy).toHaveBeenCalledTimes(2);
  });

  it('does not poll at all when the list is already complete', async () => {
    vi.useFakeTimers();
    const getSpy = vi.spyOn(apiClient, 'get').mockResolvedValue(page('complete') as never);

    renderHook(() => useJudgmentLists({ query_set_id: 'qs1' }, { refetchInterval: POLL }), {
      wrapper: wrapper(),
    });

    await vi.advanceTimersByTimeAsync(0);
    expect(getSpy).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(12_000);
    expect(getSpy).toHaveBeenCalledTimes(1); // never polled
  });

  it('does not leak refetchInterval into the request params', async () => {
    const getSpy = vi.spyOn(apiClient, 'get').mockResolvedValue(page('complete') as never);
    renderHook(
      () =>
        useJudgmentLists({ query_set_id: 'qs1', target: 'products' }, { refetchInterval: 4000 }),
      { wrapper: wrapper() },
    );
    await new Promise((r) => setTimeout(r, 10));
    expect(getSpy).toHaveBeenCalledWith('/api/v1/judgment-lists', {
      params: {
        query_set_id: 'qs1',
        cluster_id: undefined,
        target: 'products',
        cursor: undefined,
        limit: undefined,
      },
    });
  });
});
