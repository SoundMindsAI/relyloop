// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type ReactNode } from 'react';

import { server } from '../../setup';
import { useStudies, useStudy, useStudyTrials } from '@/lib/api/studies';

const API_BASE = 'http://api.test';

function wrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

describe('useStudies', () => {
  it('encodes filter params and parses X-Total-Count', async () => {
    let capturedUrl = '';
    server.use(
      http.get(`${API_BASE}/api/v1/studies`, ({ request }) => {
        capturedUrl = request.url;
        return HttpResponse.json(
          { data: [], next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '7' } },
        );
      }),
    );
    const { result } = renderHook(
      () => useStudies({ status: 'running', cluster_id: 'c1', limit: 25 }),
      { wrapper: wrapper() },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.totalCount).toBe(7);
    const url = new URL(capturedUrl);
    expect(url.searchParams.get('status')).toBe('running');
    expect(url.searchParams.get('cluster_id')).toBe('c1');
    expect(url.searchParams.get('limit')).toBe('25');
  });

  it('omits undefined params from the query string', async () => {
    let capturedUrl = '';
    server.use(
      http.get(`${API_BASE}/api/v1/studies`, ({ request }) => {
        capturedUrl = request.url;
        return HttpResponse.json({ data: [], next_cursor: null, has_more: false });
      }),
    );
    const { result } = renderHook(() => useStudies({ status: 'running' }), {
      wrapper: wrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const url = new URL(capturedUrl);
    expect(url.searchParams.has('cluster_id')).toBe(false);
    expect(url.searchParams.has('cursor')).toBe(false);
  });
});

describe('useStudy', () => {
  it('fetches by id', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/studies/abc`, () =>
        HttpResponse.json({ id: 'abc', name: 'demo', status: 'running' }),
      ),
    );
    const { result } = renderHook(() => useStudy('abc'), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.id).toBe('abc');
  });
});

describe('useStudyTrials', () => {
  it('sends sort + cursor params', async () => {
    let capturedUrl = '';
    server.use(
      http.get(`${API_BASE}/api/v1/studies/abc/trials`, ({ request }) => {
        capturedUrl = request.url;
        return HttpResponse.json(
          { data: [], next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '0' } },
        );
      }),
    );
    const { result } = renderHook(
      () => useStudyTrials('abc', { sort: 'primary_metric_desc', cursor: 'cur1', limit: 10 }),
      { wrapper: wrapper() },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const url = new URL(capturedUrl);
    expect(url.searchParams.get('sort')).toBe('primary_metric_desc');
    expect(url.searchParams.get('cursor')).toBe('cur1');
    expect(url.searchParams.get('limit')).toBe('10');
  });
});
