/**
 * RelyLoop API client.
 *
 * Wraps `fetch` with:
 *   - `X-Request-ID: <UUIDv7>` injection on every request (server-side log correlation).
 *   - Structured error-envelope translation → `ApiError` (per docs/01_architecture/api-conventions.md).
 *   - Retry policy: 1 initial attempt + up to 3 retries = 4 total attempts max,
 *     with 1000ms / 2000ms / 4000ms waits between retries. Retries fire on:
 *       - 503 with `retryable=true` (transient backend / dependency unavailability)
 *       - Network failure (`fetch` rejects with `TypeError` — connection refused, DNS, etc.)
 *     4xx (non-503) and 5xx (non-503-retryable) throw immediately.
 *
 * Use the `apiClient` singleton from this module; do NOT call `fetch` directly.
 */

import { ApiError } from './api-errors';
import { uuidv7 } from './uuid';

const DEFAULT_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000';
const PER_ATTEMPT_TIMEOUT_MS = 30_000;
const RETRY_WAITS_MS: readonly number[] = [1000, 2000, 4000];

export type ApiClientOptions = {
  baseUrl?: string;
  fetchImpl?: typeof fetch;
  /** Override per-attempt timeout — primarily for tests that use fake timers. */
  perAttemptTimeoutMs?: number;
  /** Override retry waits — primarily for tests. Length determines max retries. */
  retryWaitsMs?: readonly number[];
};

export type RequestOptions = RequestInit & {
  params?: Record<string, string | number | boolean | undefined | null>;
};

export type ApiResponse<T> = {
  data: T;
  headers: Headers;
};

export interface ApiClient {
  get<T>(path: string, init?: RequestOptions): Promise<ApiResponse<T>>;
  post<T>(path: string, body: unknown, init?: RequestOptions): Promise<ApiResponse<T>>;
  patch<T>(path: string, body: unknown, init?: RequestOptions): Promise<ApiResponse<T>>;
  delete<T>(path: string, init?: RequestOptions): Promise<ApiResponse<T>>;
  /** POST a raw CSV body. Used by `POST /query-sets` and `POST /query-sets/{id}/queries`. */
  postCsv<T>(path: string, csvBody: string, init?: RequestOptions): Promise<ApiResponse<T>>;
}

function encodeParams(params: RequestOptions['params']): string {
  if (!params) return '';
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null) continue;
    qs.append(k, String(v));
  }
  const s = qs.toString();
  return s ? `?${s}` : '';
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener('abort', () => {
      clearTimeout(t);
      reject(new DOMException('Aborted', 'AbortError'));
    });
  });
}

type EnvelopeShape = { detail?: { error_code?: string; message?: string; retryable?: boolean } };

function parseEnvelope(body: unknown): { errorCode: string; message: string; retryable: boolean } {
  if (body && typeof body === 'object') {
    const detail = (body as EnvelopeShape).detail;
    if (detail && typeof detail === 'object') {
      const errorCode =
        typeof detail.error_code === 'string' ? detail.error_code : 'INTERNAL_ERROR';
      const message = typeof detail.message === 'string' ? detail.message : 'Unknown error';
      const retryable = typeof detail.retryable === 'boolean' ? detail.retryable : false;
      return { errorCode, message, retryable };
    }
  }
  return { errorCode: 'INTERNAL_ERROR', message: 'Unexpected response shape', retryable: false };
}

async function readJsonSafe(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function makeNetworkError(): ApiError {
  return new ApiError({
    status: 0,
    errorCode: 'SERVICE_UNAVAILABLE',
    message: 'Backend unreachable',
    retryable: true,
    requestId: null,
  });
}

export function createApiClient(options: ApiClientOptions = {}): ApiClient {
  const baseUrl = options.baseUrl ?? DEFAULT_BASE_URL;
  // Read `globalThis.fetch` at call time, NOT at construction time. msw and
  // similar request interceptors replace `globalThis.fetch` during their
  // `beforeAll` setup, which runs AFTER this module is first imported. Capturing
  // a bound reference here would silently bypass the interceptor.
  const fetchImpl: typeof fetch =
    options.fetchImpl ?? ((input, init) => globalThis.fetch(input, init));
  const perAttemptTimeoutMs = options.perAttemptTimeoutMs ?? PER_ATTEMPT_TIMEOUT_MS;
  const retryWaits = options.retryWaitsMs ?? RETRY_WAITS_MS;
  const maxAttempts = retryWaits.length + 1;

  async function attempt(
    url: string,
    init: RequestInit,
  ): Promise<
    { kind: 'ok'; response: Response } | { kind: 'network-error' } | { kind: 'user-aborted' }
  > {
    const timeoutController = new AbortController();
    const timeoutId = setTimeout(() => timeoutController.abort(), perAttemptTimeoutMs);
    // Compose: user-provided signal (if any) + our timeout signal. We use
    // AbortSignal.any() when available; fall back to timeout-only otherwise.
    const userSignal = init.signal ?? null;
    const anyFn = (AbortSignal as unknown as { any?: (signals: AbortSignal[]) => AbortSignal }).any;
    const composedSignal =
      userSignal && anyFn
        ? anyFn([userSignal, timeoutController.signal])
        : timeoutController.signal;
    try {
      const response = await fetchImpl(url, { ...init, signal: composedSignal });
      return { kind: 'ok', response };
    } catch (err) {
      // fetch() rejects with TypeError on network failures (DNS, connection refused),
      // and with AbortError when EITHER the timeout fires OR the caller aborted.
      // We distinguish: if the caller's signal aborted, the request was user-cancelled
      // and must NOT retry. If the timeout fired (or no caller signal exists), retry.
      if (err instanceof DOMException && err.name === 'AbortError') {
        if (userSignal?.aborted) {
          return { kind: 'user-aborted' };
        }
        return { kind: 'network-error' };
      }
      if (err instanceof TypeError) {
        return { kind: 'network-error' };
      }
      throw err;
    } finally {
      clearTimeout(timeoutId);
    }
  }

  async function execute<T>(
    method: string,
    path: string,
    body: BodyInit | null,
    extraHeaders: HeadersInit,
    requestOptions: RequestOptions | undefined,
  ): Promise<ApiResponse<T>> {
    const { params, headers: callerHeaders, ...restInit } = requestOptions ?? {};
    const url = `${baseUrl}${path}${encodeParams(params)}`;
    const headers = new Headers(extraHeaders);
    if (callerHeaders) {
      for (const [k, v] of new Headers(callerHeaders).entries()) headers.set(k, v);
    }
    headers.set('X-Request-ID', uuidv7());
    headers.set('Accept', 'application/json');

    const init: RequestInit = { ...restInit, method, headers, body };

    let lastApiError: ApiError | null = null;
    for (let attemptIdx = 0; attemptIdx < maxAttempts; attemptIdx++) {
      const result = await attempt(url, init);

      if (result.kind === 'user-aborted') {
        // Caller explicitly cancelled. Do NOT retry — surface immediately as an
        // AbortError-shaped ApiError so callers can branch on errorCode if needed.
        throw new ApiError({
          status: 0,
          errorCode: 'REQUEST_ABORTED',
          message: 'Request aborted by caller',
          retryable: false,
          requestId: null,
        });
      }

      if (result.kind === 'network-error') {
        lastApiError = makeNetworkError();
        // Network failures are retryable — fall through to backoff.
      } else {
        const response = result.response;
        const requestId = response.headers.get('X-Request-ID');
        if (response.ok) {
          const data = (await readJsonSafe(response)) as T;
          return { data, headers: response.headers };
        }

        const envelope = parseEnvelope(await readJsonSafe(response));
        const apiError = new ApiError({
          status: response.status,
          errorCode: envelope.errorCode,
          message: envelope.message,
          retryable: envelope.retryable,
          requestId,
        });

        // Only 503 + retryable=true triggers backoff. All other errors throw immediately.
        if (response.status !== 503 || !envelope.retryable) {
          throw apiError;
        }
        lastApiError = apiError;
      }

      // We're going to retry — if there are no more retry slots, throw the last error.
      // attemptIdx is bounded by maxAttempts (= retryWaits.length + 1); the access is
      // safe by construction. retryWaits is a readonly closed-over array, not user input.
      // eslint-disable-next-line security/detect-object-injection
      const nextWait = retryWaits[attemptIdx];
      if (nextWait === undefined) {
        throw lastApiError ?? makeNetworkError();
      }
      await sleep(nextWait);
    }

    // Unreachable in practice — loop either returns or throws — but TypeScript needs it.
    throw lastApiError ?? makeNetworkError();
  }

  return {
    get<T>(path: string, init?: RequestOptions) {
      return execute<T>('GET', path, null, { 'Content-Type': 'application/json' }, init);
    },
    post<T>(path: string, body: unknown, init?: RequestOptions) {
      return execute<T>(
        'POST',
        path,
        JSON.stringify(body),
        { 'Content-Type': 'application/json' },
        init,
      );
    },
    patch<T>(path: string, body: unknown, init?: RequestOptions) {
      return execute<T>(
        'PATCH',
        path,
        JSON.stringify(body),
        { 'Content-Type': 'application/json' },
        init,
      );
    },
    delete<T>(path: string, init?: RequestOptions) {
      return execute<T>('DELETE', path, null, { 'Content-Type': 'application/json' }, init);
    },
    postCsv<T>(path: string, csvBody: string, init?: RequestOptions) {
      return execute<T>('POST', path, csvBody, { 'Content-Type': 'text/csv' }, init);
    },
  };
}

export const apiClient: ApiClient = createApiClient();
