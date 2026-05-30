// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * feat_create_study_target_autocomplete Story F1 unit tests for the two
 * cluster API hooks: `useClusterTargets` (new) and `useClusterSchema` (tuned).
 *
 * The retry-count assertions mock at the `apiClient.get` layer (NOT the
 * network layer via msw) so we isolate TanStack's retry-predicate behavior
 * from the api-client's own internal 503 retry loop. The combined behavior
 * at the network layer (api-client × TanStack = up to 16 calls on 503) is
 * covered separately by `api-client.test.ts`.
 *
 * Source contracts:
 *   - feature_spec.md FR-3, FR-6, AC-6, AC-11, AC-13
 *   - implementation_plan.md Story F1 DoD
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { type ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { apiClient } from '@/lib/api-client';
import { ApiError } from '@/lib/api-errors';
import { useClusterSchema, useClusterTargets } from '@/lib/api/clusters';

const toastErrorMock = vi.fn();
vi.mock('sonner', async () => {
  const actual = await vi.importActual<typeof import('sonner')>('sonner');
  return {
    ...actual,
    toast: { ...actual.toast, error: toastErrorMock },
  };
});

function wrapper() {
  // Disable retry delay so the retry-predicate path runs immediately under
  // jest-fake-timers-free vitest. `retry: undefined` means hook-level retry
  // config (the one we're testing) wins.
  const client = new QueryClient({
    defaultOptions: {
      queries: { retryDelay: 0 },
      mutations: { retry: false },
    },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

beforeEach(() => {
  toastErrorMock.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('useClusterTargets', () => {
  it('returns the bare { data } shape directly from the API (AC-6)', async () => {
    const apiGetSpy = vi.spyOn(apiClient, 'get').mockResolvedValue({
      data: { data: [{ name: 'products', doc_count: 42 }] },
      headers: new Headers(),
    });
    const { result } = renderHook(() => useClusterTargets('c-123'), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual({ data: [{ name: 'products', doc_count: 42 }] });
    expect(apiGetSpy).toHaveBeenCalledTimes(1);
    expect(apiGetSpy).toHaveBeenCalledWith('/api/v1/clusters/c-123/targets');
  });

  it('does not fire a GET when clusterId is empty (enabled: false)', async () => {
    const apiGetSpy = vi.spyOn(apiClient, 'get').mockResolvedValue({
      data: { data: [] },
      headers: new Headers(),
    });
    const { result } = renderHook(() => useClusterTargets(''), { wrapper: wrapper() });
    // Wait a tick to ensure no queryFn runs.
    await new Promise((r) => setTimeout(r, 10));
    expect(result.current.fetchStatus).toBe('idle');
    expect(apiGetSpy).not.toHaveBeenCalled();
  });

  it('fires exactly one GET on TARGETS_FORBIDDEN, no toast (AC-13)', async () => {
    const forbidden = new ApiError({
      message: 'cluster denied listing call',
      errorCode: 'TARGETS_FORBIDDEN',
      retryable: false,
      status: 403,
    });
    const apiGetSpy = vi.spyOn(apiClient, 'get').mockRejectedValue(forbidden);
    const { result } = renderHook(() => useClusterTargets('c-acl'), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(apiGetSpy).toHaveBeenCalledTimes(1);
    expect(toastErrorMock).not.toHaveBeenCalled();
  });

  it('fires exactly one GET on CLUSTER_NOT_FOUND (retryable: false)', async () => {
    const notFound = new ApiError({
      message: 'cluster ... not found',
      errorCode: 'CLUSTER_NOT_FOUND',
      retryable: false,
      status: 404,
    });
    const apiGetSpy = vi.spyOn(apiClient, 'get').mockRejectedValue(notFound);
    const { result } = renderHook(() => useClusterTargets('missing'), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(apiGetSpy).toHaveBeenCalledTimes(1);
  });

  it('fires up to 4 GETs on CLUSTER_UNREACHABLE (retryable: true, default 3 retries)', async () => {
    const unreachable = new ApiError({
      message: 'HTTP 503',
      errorCode: 'CLUSTER_UNREACHABLE',
      retryable: true,
      status: 503,
    });
    const apiGetSpy = vi.spyOn(apiClient, 'get').mockRejectedValue(unreachable);
    const { result } = renderHook(() => useClusterTargets('c-down'), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.isError).toBe(true), { timeout: 2000 });
    expect(apiGetSpy).toHaveBeenCalledTimes(4); // 1 initial + 3 retries
  });
});

describe('useClusterSchema (FR-6 tune)', () => {
  it('fires exactly one GET on TARGET_NOT_FOUND, no toast (AC-11 hook-level)', async () => {
    const notFound = new ApiError({
      message: "target 'prodd' not found",
      errorCode: 'TARGET_NOT_FOUND',
      retryable: false,
      status: 404,
    });
    const apiGetSpy = vi.spyOn(apiClient, 'get').mockRejectedValue(notFound);
    const { result } = renderHook(() => useClusterSchema('c-1', 'prodd'), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(apiGetSpy).toHaveBeenCalledTimes(1);
    expect(toastErrorMock).not.toHaveBeenCalled();
  });

  it('still retries up to 4 GETs on CLUSTER_UNREACHABLE (regression check)', async () => {
    const unreachable = new ApiError({
      message: 'HTTP 503',
      errorCode: 'CLUSTER_UNREACHABLE',
      retryable: true,
      status: 503,
    });
    const apiGetSpy = vi.spyOn(apiClient, 'get').mockRejectedValue(unreachable);
    const { result } = renderHook(() => useClusterSchema('c-1', 'products'), {
      wrapper: wrapper(),
    });
    await waitFor(() => expect(result.current.isError).toBe(true), { timeout: 2000 });
    expect(apiGetSpy).toHaveBeenCalledTimes(4);
  });

  it('passes target as a query param on the wire (happy path)', async () => {
    const apiGetSpy = vi.spyOn(apiClient, 'get').mockResolvedValue({
      data: { name: 'products', fields: [{ name: 'title', type: 'text' }] },
      headers: new Headers(),
    });
    const { result } = renderHook(() => useClusterSchema('c-1', 'products'), {
      wrapper: wrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiGetSpy).toHaveBeenCalledWith('/api/v1/clusters/c-1/schema', {
      params: { target: 'products' },
    });
  });
});
