import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { server } from '../setup';
import { createApiClient } from '@/lib/api-client';
import { ApiError, isApiError } from '@/lib/api-errors';

const BASE = 'http://api.test';

function client(overrides = {}) {
  return createApiClient({
    baseUrl: BASE,
    // Short waits so tests can advance fake timers without spelling out 1000/2000/4000.
    retryWaitsMs: [10, 20, 40],
    perAttemptTimeoutMs: 5_000,
    ...overrides,
  });
}

describe('apiClient header injection', () => {
  it('sends X-Request-ID on every request', async () => {
    const seen: string[] = [];
    server.use(
      http.get(`${BASE}/api/v1/clusters`, ({ request }) => {
        const id = request.headers.get('X-Request-ID');
        if (id) seen.push(id);
        return HttpResponse.json({ data: [], next_cursor: null, has_more: false });
      }),
    );
    const c = client();
    await c.get('/api/v1/clusters');
    await c.get('/api/v1/clusters');
    expect(seen).toHaveLength(2);
    expect(seen[0]).toMatch(/^[0-9a-f-]{36}$/);
    expect(seen[0]).not.toBe(seen[1]);
  });

  it('exposes X-Total-Count on the response headers', async () => {
    server.use(
      http.get(`${BASE}/api/v1/studies`, () =>
        HttpResponse.json(
          { data: [], next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '42' } },
        ),
      ),
    );
    const c = client();
    const r = await c.get('/api/v1/studies');
    expect(r.headers.get('X-Total-Count')).toBe('42');
  });
});

describe('apiClient error envelope translation', () => {
  it('translates 4xx envelope to ApiError', async () => {
    server.use(
      http.post(`${BASE}/api/v1/clusters`, () =>
        HttpResponse.json(
          {
            detail: {
              error_code: 'CLUSTER_UNREACHABLE',
              message: 'Cannot reach https://es.example',
              retryable: true,
            },
          },
          { status: 400 },
        ),
      ),
    );
    const c = client();
    await expect(c.post('/api/v1/clusters', { name: 'p' })).rejects.toBeInstanceOf(ApiError);
    try {
      await c.post('/api/v1/clusters', { name: 'p' });
    } catch (err) {
      expect(isApiError(err)).toBe(true);
      if (isApiError(err)) {
        expect(err.status).toBe(400);
        expect(err.errorCode).toBe('CLUSTER_UNREACHABLE');
        expect(err.retryable).toBe(true);
      }
    }
  });

  it('falls back to INTERNAL_ERROR when body is not the envelope shape', async () => {
    server.use(http.get(`${BASE}/x`, () => HttpResponse.text('plain text body', { status: 500 })));
    const c = client();
    try {
      await c.get('/x');
      throw new Error('should have thrown');
    } catch (err) {
      expect(isApiError(err)).toBe(true);
      if (isApiError(err)) {
        expect(err.status).toBe(500);
        expect(err.errorCode).toBe('INTERNAL_ERROR');
      }
    }
  });
});

describe('apiClient retry policy', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('503 retryable=true executes 4 total attempts (1 initial + 3 retries)', async () => {
    let attempts = 0;
    server.use(
      http.get(`${BASE}/flaky`, () => {
        attempts++;
        return HttpResponse.json(
          { detail: { error_code: 'SERVICE_UNAVAILABLE', message: 'down', retryable: true } },
          { status: 503 },
        );
      }),
    );
    const c = client();
    const promise = c.get('/flaky').catch((err) => err);
    // Drain timers: 3 waits at 10, 20, 40 ms — runAllTimersAsync handles them all.
    await vi.runAllTimersAsync();
    const result = await promise;
    expect(isApiError(result)).toBe(true);
    expect(attempts).toBe(4);
  });

  it('503 retryable=false throws on the first attempt (no retries)', async () => {
    let attempts = 0;
    server.use(
      http.get(`${BASE}/hard-down`, () => {
        attempts++;
        return HttpResponse.json(
          { detail: { error_code: 'SERVICE_UNAVAILABLE', message: 'down', retryable: false } },
          { status: 503 },
        );
      }),
    );
    const c = client();
    const promise = c.get('/hard-down').catch((err) => err);
    await vi.runAllTimersAsync();
    const result = await promise;
    expect(isApiError(result)).toBe(true);
    expect(attempts).toBe(1);
  });

  it('500 non-retryable throws on the first attempt', async () => {
    let attempts = 0;
    server.use(
      http.get(`${BASE}/boom`, () => {
        attempts++;
        return HttpResponse.json(
          { detail: { error_code: 'INTERNAL_ERROR', message: 'boom', retryable: false } },
          { status: 500 },
        );
      }),
    );
    const c = client();
    const promise = c.get('/boom').catch((err) => err);
    await vi.runAllTimersAsync();
    const result = await promise;
    expect(isApiError(result)).toBe(true);
    expect(attempts).toBe(1);
  });

  it('network failure (HttpResponse.error) executes 4 total attempts then throws SERVICE_UNAVAILABLE', async () => {
    let attempts = 0;
    server.use(
      http.get(`${BASE}/nope`, () => {
        attempts++;
        return HttpResponse.error();
      }),
    );
    const c = client();
    const promise = c.get('/nope').catch((err) => err);
    await vi.runAllTimersAsync();
    const result = await promise;
    expect(isApiError(result)).toBe(true);
    if (isApiError(result)) {
      expect(result.errorCode).toBe('SERVICE_UNAVAILABLE');
      expect(result.status).toBe(0);
    }
    expect(attempts).toBe(4);
  });

  it('default retry waits are exactly 1000/2000/4000 ms (F6)', async () => {
    // This test uses the default client (no retryWaitsMs override) to verify
    // the public contract from FR-10. We advance fake timers by exactly the
    // documented backoff intervals and confirm each advance unblocks the next attempt.
    let attempts = 0;
    server.use(
      http.get(`${BASE}/default-waits`, () => {
        attempts++;
        return HttpResponse.json(
          { detail: { error_code: 'SERVICE_UNAVAILABLE', message: 'down', retryable: true } },
          { status: 503 },
        );
      }),
    );
    // Use a client with default retry waits + short per-attempt timeout so the
    // fetch itself doesn't time out before backoff fires.
    const c = createApiClient({ baseUrl: BASE, perAttemptTimeoutMs: 100 });
    const promise = c.get('/default-waits').catch((err) => err);
    // Initial attempt fires synchronously. Then we advance through the 3 backoffs.
    await vi.advanceTimersByTimeAsync(0); // let initial attempt resolve
    expect(attempts).toBe(1);
    await vi.advanceTimersByTimeAsync(1000); // unlock retry #1
    expect(attempts).toBe(2);
    await vi.advanceTimersByTimeAsync(2000); // unlock retry #2
    expect(attempts).toBe(3);
    await vi.advanceTimersByTimeAsync(4000); // unlock retry #3
    expect(attempts).toBe(4);
    await vi.advanceTimersByTimeAsync(8000); // no more retries — would be #4 if we ran them
    expect(attempts).toBe(4);
    const result = await promise;
    expect(isApiError(result)).toBe(true);
  });

  it('user-issued abort does NOT retry (F7)', async () => {
    // Inject a fetchImpl that observes the caller's signal and rejects
    // with AbortError. The client must surface REQUEST_ABORTED on the
    // first attempt — never retry.
    vi.useRealTimers(); // bypass the suite's fake-timers for this single test
    let attempts = 0;
    const fakeFetch = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      attempts++;
      // Reject immediately as if the caller had already aborted.
      if (init?.signal?.aborted) {
        throw new DOMException('Aborted', 'AbortError');
      }
      // Otherwise wait for the abort signal to fire.
      return await new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () =>
          reject(new DOMException('Aborted', 'AbortError')),
        );
      });
    });
    const c = createApiClient({
      baseUrl: BASE,
      fetchImpl: fakeFetch as unknown as typeof fetch,
      retryWaitsMs: [1, 2, 4],
    });
    const controller = new AbortController();
    const promise = c.get('/cancellable', { signal: controller.signal }).catch((err) => err);
    // Microtask + abort.
    await Promise.resolve();
    controller.abort();
    const result = await promise;
    expect(isApiError(result)).toBe(true);
    if (isApiError(result)) {
      expect(result.errorCode).toBe('REQUEST_ABORTED');
    }
    expect(attempts).toBe(1);
  });

  it('first retryable, then success, returns success without throwing', async () => {
    let attempts = 0;
    server.use(
      http.get(`${BASE}/recovers`, () => {
        attempts++;
        if (attempts < 2) {
          return HttpResponse.json(
            { detail: { error_code: 'SERVICE_UNAVAILABLE', message: 'down', retryable: true } },
            { status: 503 },
          );
        }
        return HttpResponse.json({ data: 'ok' });
      }),
    );
    const c = client();
    const promise = c.get<{ data: string }>('/recovers');
    await vi.runAllTimersAsync();
    const result = await promise;
    expect(result.data).toEqual({ data: 'ok' });
    expect(attempts).toBe(2);
  });
});

describe('apiClient methods', () => {
  it('patch sends Content-Type: application/json with JSON-encoded body', async () => {
    let receivedContentType: string | null = null;
    let receivedBody: string | null = null;
    server.use(
      http.patch(`${BASE}/x/1`, async ({ request }) => {
        receivedContentType = request.headers.get('Content-Type');
        receivedBody = await request.text();
        return HttpResponse.json({ id: '1', updated: true });
      }),
    );
    const c = client();
    const r = await c.patch<{ id: string; updated: boolean }>('/x/1', { name: 'new' });
    expect(receivedContentType).toBe('application/json');
    expect(receivedBody).toBe(JSON.stringify({ name: 'new' }));
    expect(r.data.updated).toBe(true);
  });

  it('delete sends DELETE method with no body', async () => {
    let receivedBody: string | null = null;
    let receivedMethod: string | null = null;
    server.use(
      http.delete(`${BASE}/x/1`, async ({ request }) => {
        receivedMethod = request.method;
        receivedBody = await request.text();
        return HttpResponse.json({ deleted: true });
      }),
    );
    const c = client();
    const r = await c.delete<{ deleted: boolean }>('/x/1');
    expect(receivedMethod).toBe('DELETE');
    expect(receivedBody).toBe('');
    expect(r.data.deleted).toBe(true);
  });

  it('postCsv sends Content-Type: text/csv with the raw body', async () => {
    let receivedContentType: string | null = null;
    let receivedBody: string | null = null;
    server.use(
      http.post(`${BASE}/api/v1/query-sets`, async ({ request }) => {
        receivedContentType = request.headers.get('Content-Type');
        receivedBody = await request.text();
        return HttpResponse.json({ id: 'x' }, { status: 201 });
      }),
    );
    const c = client();
    await c.postCsv('/api/v1/query-sets', 'query_text\nhello world');
    expect(receivedContentType).toBe('text/csv');
    expect(receivedBody).toBe('query_text\nhello world');
  });

  it('params get url-encoded', async () => {
    let url: string | null = null;
    server.use(
      http.get(`${BASE}/api/v1/studies`, ({ request }) => {
        url = new URL(request.url).search;
        return HttpResponse.json({ data: [], next_cursor: null, has_more: false });
      }),
    );
    const c = client();
    await c.get('/api/v1/studies', { params: { status: 'running', limit: 10, since: undefined } });
    expect(url).toBe('?status=running&limit=10');
  });
});
