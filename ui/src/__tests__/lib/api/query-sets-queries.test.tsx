/**
 * Hook tests for the per-query CRUD hooks (feat_query_inline_crud Story 4.0).
 *
 * useQueries / useUpdateQuery / useDeleteQuery. Asserts:
 * - GET assembles the QueriesPage shape with totalCount from X-Total-Count
 * - PATCH invalidates ['query-sets', id, 'queries'] AND ['query-sets', id]
 * - DELETE 204 invalidates the same keys + emits 'Query deleted' toast
 * - DELETE has meta.suppressGlobalErrorToast so the global handler is bypassed
 */
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type ReactNode } from 'react';
import { toast } from 'sonner';

import { server } from '../../setup';
import { useDeleteQuery, useQueries, useUpdateQuery } from '@/lib/api/query-sets';

const API_BASE = 'http://api.test';
const QS_ID = 'qs-1';

function wrap(qc: QueryClient) {
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  }
  return Wrapper;
}

describe('useQueries', () => {
  it('returns QueriesPage with totalCount from X-Total-Count', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/query-sets/${QS_ID}/queries`, () =>
        HttpResponse.json(
          { data: [], next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '42' } },
        ),
      ),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useQueries(QS_ID), { wrapper: wrap(qc) });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.totalCount).toBe(42);
    expect(result.current.data?.has_more).toBe(false);
  });
});

describe('useUpdateQuery', () => {
  it('invalidates both queries-list and query-set keys on success', async () => {
    server.use(
      http.patch(`${API_BASE}/api/v1/query-sets/${QS_ID}/queries/q1`, () =>
        HttpResponse.json({
          id: 'q1',
          query_text: 'new',
          reference_answer: null,
          query_metadata: null,
          judgment_count: 0,
        }),
      ),
      http.get(`${API_BASE}/api/v1/query-sets/${QS_ID}/queries`, () =>
        HttpResponse.json(
          { data: [], next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '0' } },
        ),
      ),
    );

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    // Seed both query caches so we can assert invalidation.
    qc.setQueryData(['query-sets', QS_ID, 'queries', {}], { data: [] });
    qc.setQueryData(['query-sets', QS_ID], { name: 'qs' });

    const invalidateSpy = vi.spyOn(qc, 'invalidateQueries');

    const { result } = renderHook(() => useUpdateQuery(QS_ID), { wrapper: wrap(qc) });
    result.current.mutate({ queryId: 'q1', patch: { query_text: 'new' } });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['query-sets', QS_ID, 'queries'] });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['query-sets', QS_ID] });
  });
});

describe('useDeleteQuery', () => {
  it('has meta.suppressGlobalErrorToast set', async () => {
    server.use(
      http.delete(
        `${API_BASE}/api/v1/query-sets/${QS_ID}/queries/q1`,
        () => new HttpResponse(null, { status: 204 }),
      ),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(
      () =>
        useDeleteQuery(QS_ID, {
          onOpenJudgmentList: () => {},
        }),
      { wrapper: wrap(qc) },
    );
    // The mutation's meta is exposed via the options it was constructed with.
    // We can introspect by triggering the mutation and asking the cache.
    result.current.mutate('q1');
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    // After mutate, the running mutation's meta is on the mutation observer.
    // Simplest check: poke the cache and verify a mutation exists with the meta.
    const mutations = qc.getMutationCache().getAll();
    const ours = mutations.find((m) => m.options.meta?.suppressGlobalErrorToast === true);
    expect(ours).toBeDefined();
  });

  it('204 emits success toast and invalidates caches', async () => {
    const toastSpy = vi.spyOn(toast, 'success');
    server.use(
      http.delete(
        `${API_BASE}/api/v1/query-sets/${QS_ID}/queries/q1`,
        () => new HttpResponse(null, { status: 204 }),
      ),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidateSpy = vi.spyOn(qc, 'invalidateQueries');
    const onSuccessMock = vi.fn();
    const { result } = renderHook(
      () =>
        useDeleteQuery(QS_ID, {
          onOpenJudgmentList: () => {},
          onSuccess: onSuccessMock,
        }),
      { wrapper: wrap(qc) },
    );
    result.current.mutate('q1');
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(toastSpy).toHaveBeenCalledWith('Query deleted');
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['query-sets', QS_ID, 'queries'] });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['query-sets', QS_ID] });
    expect(onSuccessMock).toHaveBeenCalled();
    toastSpy.mockRestore();
  });
});
