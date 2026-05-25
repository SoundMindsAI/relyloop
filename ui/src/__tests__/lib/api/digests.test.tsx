/**
 * feat_study_clone_narrow_bounds Story 1.2 — tests for the widened
 * ``useStudyDigest`` signature.
 *
 * The hook gained an optional ``{ enabled? }`` opts argument (mirroring
 * ``useStudy(id, { enabled })``) so the create-study modal can call the
 * hook unconditionally (Rules of Hooks) without firing a network request
 * on the non-clone path.
 *
 * Default ``enabled: opts?.enabled ?? Boolean(studyId)`` keeps existing
 * single-argument callers working unchanged.
 */

import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type ReactNode } from 'react';

import { server } from '../../setup';
import { useStudyDigest } from '@/lib/api/digests';

const API_BASE = 'http://api.test';

function wrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

describe('useStudyDigest — backward-compat single-arg form', () => {
  it('fires the request when called with just a studyId', async () => {
    let fetchCount = 0;
    server.use(
      http.get(`${API_BASE}/api/v1/studies/abc/digest`, () => {
        fetchCount += 1;
        return HttpResponse.json({
          id: 'dig-1',
          study_id: 'abc',
          narrative: 'n',
          parameter_importance: {},
          recommended_config: { title_boost: 2.0 },
          suggested_followups: [],
          generated_by: 'test',
          generated_at: '2026-05-25T00:00:00Z',
        });
      }),
    );
    const { result } = renderHook(() => useStudyDigest('abc'), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(fetchCount).toBe(1);
    expect(result.current.data?.recommended_config).toEqual({ title_boost: 2.0 });
  });
});

describe('useStudyDigest — enabled gate (widened signature)', () => {
  it('does NOT fire the request when studyId is undefined', async () => {
    let fetchCount = 0;
    server.use(
      http.get(`${API_BASE}/api/v1/studies/*/digest`, () => {
        fetchCount += 1;
        return HttpResponse.json({});
      }),
    );
    const { result } = renderHook(() => useStudyDigest(undefined), {
      wrapper: wrapper(),
    });
    // Idle / disabled — react-query exposes this as fetchStatus === 'idle'.
    await waitFor(() => expect(result.current.fetchStatus).toBe('idle'));
    expect(fetchCount).toBe(0);
    expect(result.current.isSuccess).toBe(false);
  });

  it('does NOT fire when opts.enabled is explicitly false (even with a real studyId)', async () => {
    let fetchCount = 0;
    server.use(
      http.get(`${API_BASE}/api/v1/studies/abc/digest`, () => {
        fetchCount += 1;
        return HttpResponse.json({});
      }),
    );
    const { result } = renderHook(() => useStudyDigest('abc', { enabled: false }), {
      wrapper: wrapper(),
    });
    await waitFor(() => expect(result.current.fetchStatus).toBe('idle'));
    expect(fetchCount).toBe(0);
  });

  it('does fire when opts.enabled is explicitly true with a truthy studyId', async () => {
    let fetchCount = 0;
    server.use(
      http.get(`${API_BASE}/api/v1/studies/abc/digest`, () => {
        fetchCount += 1;
        return HttpResponse.json({
          id: 'dig-1',
          study_id: 'abc',
          narrative: 'n',
          parameter_importance: {},
          recommended_config: {},
          suggested_followups: [],
          generated_by: 'test',
          generated_at: '2026-05-25T00:00:00Z',
        });
      }),
    );
    const { result } = renderHook(() => useStudyDigest('abc', { enabled: true }), {
      wrapper: wrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(fetchCount).toBe(1);
  });
});
